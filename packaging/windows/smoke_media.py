"""Exercise media extraction and the normalized PCM inference path offline."""

import io
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import wave

import numpy as np

from aheadsubs.automation import media_duration
from aheadsubs.inference.providers import Cue, FasterWhisper
from aheadsubs.server.engine import extract_audio


def main(folder):
    mp4 = folder / "aac.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=220:44100:duration=1",
        "-c:a", "aac", str(mp4),
    ], check=True, timeout=20)
    assert abs(media_duration(mp4, 0, 10) - 1) < .01
    with wave.open(io.BytesIO(extract_audio(mp4, 0, .25, .5)), "rb") as audio:
        assert audio.getnframes() == 8000

    media = folder / "双音轨.mkv"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", "sine=220:44100:duration=2",
        "-itsoffset", "0.75", "-f", "lavfi", "-i", "sine=440:48000:duration=1",
        "-map", "0:a", "-map", "1:a", "-c:a", "pcm_s16le", str(media),
    ], check=True, timeout=20)
    assert abs(media_duration(media, 1, 10) - 2) < .01
    wav = extract_audio(media, 1, .25, 1)
    with wave.open(io.BytesIO(wav), "rb") as audio:
        assert audio.getparams()[:3] == (1, 2, 16000)
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    first_signal = np.flatnonzero(np.abs(pcm) > 500)[0]
    assert abs(first_signal / 16000 - .5) < .002
    section = pcm[9000:11000]
    assert 50 <= np.sum((section[1:] > 0) & (section[:-1] <= 0)) <= 60

    def transcribe(samples, *, language, **options):
        assert samples.dtype == np.float32 and samples.ndim == 1
        np.testing.assert_array_equal(samples, pcm.astype(np.float32) / 32768)
        assert language == "en" and options["vad_filter"] is False
        return [SimpleNamespace(start=.5, end=1, text=" sample ")], SimpleNamespace(language="en")

    recognizer = FasterWhisper.__new__(FasterWhisper)
    recognizer.model = SimpleNamespace(transcribe=transcribe)
    assert recognizer.recognize(wav, "en") == ("en", [Cue(.5, 1, "sample")])
    print("Media smoke passed (MP4/AAC, Unicode Matroska, multiple tracks, seek timing, Whisper PCM)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
