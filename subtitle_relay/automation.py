"""Operations shared by the AheadSubs CLI and MCP server."""
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Callable
from urllib.error import URLError
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .automation_text import text
from .client import RelayClient, RelayHTTPError


DEFAULT_PORT = 8769
MediaPath = Annotated[str, Field(min_length=1, max_length=4096, description="field.path")]
Language = Annotated[str, Field(min_length=1, max_length=32)]


class OperationError(RuntimeError):
    def __init__(self, code, message=None, **values):
        super().__init__(message if message is not None else text(f"error.{code}", **values))
        self.code = code

    def result(self):
        return {"ok": False, "error": str(self), "error_code": self.code}


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Translation(Arguments):
    text: str = Field(min_length=1, max_length=4000, description="field.text")
    source: Language = Field(description="field.source")
    target: Language = Field(description="field.target")


class MediaOptions(Arguments):
    source: Language | None = Field(None, description="field.media_source")
    target: Language | None = Field(None, description="field.media_target")
    audio: int = Field(0, ge=0, le=255, description="field.audio")
    bilingual: bool | None = Field(None, description="field.bilingual")

    def playback_options(self):
        options = self.model_dump(include=set(MediaOptions.model_fields), exclude_unset=True)
        for key in ("target", "bilingual"):
            if options.get(key) is None:
                options.pop(key, None)
        if options.get("source") == "auto":
            options["source"] = None
        return options


class Session(Arguments):
    session: str = Field(min_length=1, max_length=100, description="field.session")


class PlaybackUpdate(Session, MediaOptions):
    path: MediaPath
    position: float = Field(ge=0, le=10_000_000, description="field.position")
    duration: float | None = Field(None, gt=0, le=10_000_000, description="field.duration")
    speed: float = Field(1, ge=0.1, le=5, description="field.speed")
    ahead: float = Field(20, ge=1, le=120, description="field.ahead")


class Generation(MediaOptions):
    path: MediaPath
    output: str = Field(min_length=1, max_length=4096, description="field.output")
    overwrite: bool = Field(False, description="field.overwrite")
    timeout: float = Field(1800, gt=0, le=86400, description="field.timeout")


def media_path(value):
    path = Path(value).resolve()
    if not path.is_file():
        raise OperationError("media_not_found")
    return path


def media_duration(path, audio, timeout):
    try:
        output = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index:format=duration",
            "-of", "json", str(path),
        ], timeout=timeout, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        metadata = json.loads(output)
        duration = float(metadata["format"]["duration"])
    except FileNotFoundError as exc:
        raise OperationError("ffprobe_not_found") from exc
    except (subprocess.CalledProcessError, ValueError, KeyError, TypeError) as exc:
        raise OperationError("invalid_media") from exc
    if not math.isfinite(duration) or not 0 < duration <= 10_000_000:
        raise OperationError("invalid_media")
    if audio >= len(metadata.get("streams", [])):
        raise OperationError("invalid_audio")
    return duration


def export_subtitle(source, output, overwrite):
    # Stage the complete SRT in the destination directory before publishing it.
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".tmp", delete=False) as staged:
        temporary = Path(staged.name)
    try:
        shutil.copyfile(source, temporary)
        if overwrite:
            temporary.replace(output)
        elif os.name == "nt":
            temporary.rename(output)
        else:
            os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def status(client, _, checkpoint):
    try:
        health = client.health()
    except (URLError, TimeoutError):
        return {"running": False, "active_sessions": 0}
    if health.get("service") != "subtitle-relay":
        raise OperationError("unexpected_service")
    return {"running": True, "active_sessions": health["active_sessions"]}


def translate_text(client, args, checkpoint):
    return client.translate_text(args.text, args.source, args.target)


def update_playback(client, args, checkpoint):
    request = args.model_dump(exclude=set(MediaOptions.model_fields), exclude_none=True)
    request.update(args.playback_options(), path=str(media_path(args.path)))
    return playback_result(client.send("playback", request))


def close_playback(client, args, checkpoint):
    return client.send("close", args.model_dump())


def playback_result(reply):
    if reply.get("error"):
        raise OperationError(reply.get("error_code") or "processing_failed", reply["error"])
    return reply


def generate_subtitles(client, args, checkpoint):
    path = media_path(args.path)
    output = Path(args.output).absolute()
    if output.suffix.lower() != ".srt" or output.resolve() == path or not output.parent.is_dir():
        raise OperationError("invalid_output")
    if not args.overwrite and (output.exists() or output.is_symlink()):
        raise FileExistsError(output)
    deadline = time.monotonic() + args.timeout

    def remaining():
        checkpoint()
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise OperationError("generation_timeout")
        return seconds

    duration = media_duration(path, args.audio, min(remaining(), 15))
    request = dict(args.playback_options(), session=uuid4().hex, path=str(path), duration=duration, ahead=60)
    position = 0.0
    generation = None
    try:
        while True:
            reply = playback_result(client.send("playback", dict(request, position=position), timeout=min(remaining(), 5)))
            if generation is not None and reply["subtitle_generation"] != generation:
                raise OperationError("generation_changed")
            generation = reply["subtitle_generation"]
            ready = reply["ready_ahead"]
            if ready >= duration - position and reply["subtitle"]:
                remaining()
                cache = Path(reply["subtitle"])
                if output.resolve() == cache.resolve():
                    raise OperationError("invalid_output")
                export_subtitle(cache, output, args.overwrite)
                return {"subtitle": str(output.resolve()), "duration": duration, "has_cues": reply["subtitle_has_cues"]}
            if ready > 0:
                position += ready
            else:
                time.sleep(min(remaining(), 0.35))
    finally:
        with suppress(OSError, RuntimeError, ValueError):
            client.send("close", {"session": request["session"]})


@dataclass(frozen=True)
class Operation:
    arguments: type[Arguments]
    run: Callable

    def schema(self):
        schema = self.arguments.model_json_schema()
        for field in schema["properties"].values():
            if "description" in field:
                field["description"] = text(field["description"])
        return schema


OPERATIONS = {
    "status": Operation(Arguments, status),
    "translate_text": Operation(Translation, translate_text),
    "generate_subtitles": Operation(Generation, generate_subtitles),
    "update_playback": Operation(PlaybackUpdate, update_playback),
    "close_playback": Operation(Session, close_playback),
}


def invoke(name, arguments, port=DEFAULT_PORT, checkpoint=lambda: None):
    if name not in OPERATIONS:
        return OperationError("unknown_operation").result()
    operation = OPERATIONS[name]
    try:
        options = operation.arguments.model_validate(arguments)
        return {"ok": True, **operation.run(RelayClient(port), options, checkpoint)}
    except ValidationError as exc:
        issue = exc.errors(include_input=False)[0]
        field = ".".join(map(str, issue["loc"])) or "arguments"
        return OperationError("invalid_arguments", field=field).result()
    except OperationError as exc:
        return exc.result()
    except RelayHTTPError as exc:
        return OperationError(exc.error_code or f"http_{exc.status}", str(exc)).result()
    except (TimeoutError, subprocess.TimeoutExpired):
        return OperationError("request_timeout").result()
    except URLError:
        return OperationError("service_unavailable", port=port).result()
    except FileExistsError:
        return OperationError("output_exists").result()
    except (OSError, ValueError, KeyError, TypeError):
        return OperationError("operation_failed").result()
