import io
import wave
from dataclasses import dataclass


@dataclass(frozen=True)
class Segmentation:
    before: float = 2
    after: float = 2
    max_speech: float = 12
    min_silence_ms: int = 450
    pad_ms: int = 160
    vad_threshold: float = 0.5
    enabled: bool = True
    backfill: float = 4


def make_wav(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    return output.getvalue()


class Segmenter:
    def __init__(self, settings):
        self.settings = settings
        if settings.enabled:
            from faster_whisper.vad import VadOptions, get_vad_model

            # Warm up the cached model here so parallel jobs share one ONNX session.
            get_vad_model()
            self.options = VadOptions(
                threshold=settings.vad_threshold,
                min_silence_duration_ms=settings.min_silence_ms,
                speech_pad_ms=settings.pad_ms,
                max_speech_duration_s=settings.max_speech,
                min_speech_duration_ms=160,
            )

    def spans(self, wav):
        with wave.open(io.BytesIO(wav), "rb") as audio:
            pcm = audio.readframes(audio.getnframes())
        if self.settings.enabled:
            import numpy as np
            from faster_whisper.vad import get_speech_timestamps

            waveform = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
            ranges = get_speech_timestamps(waveform, self.options)
        else:
            ranges = [{"start": 0, "end": len(pcm) // 2}]
        # Keep short gaps inside a request to preserve dialogue context and avoid an API call per line.
        grouped = []
        for span in ranges:
            start, end = span["start"], span["end"]
            if grouped and end - grouped[-1][0] <= self.settings.max_speech * 16000:
                grouped[-1] = (grouped[-1][0], end)
            else:
                grouped.append((start, end))
        # Silero padding can push a range slightly over the inference limit.
        limit = int(self.settings.max_speech * 16000)
        return [(part / 16000, make_wav(pcm[part * 2:min(end, part + limit) * 2]))
                for start, end in grouped for part in range(start, end, limit)]
