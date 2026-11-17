import io
import wave
from dataclasses import dataclass, replace

from .segmentation import SAMPLE_RATE, plan_spans


VAD_THRESHOLDS = {"silero": 0.5, "fsmn": 0.8}


@dataclass(frozen=True)
class Segmentation:
    before: float = 2
    after: float = 2
    max_speech: float = 12
    min_silence_ms: int = 450
    pad_ms: int = 80
    vad_threshold: float = 0.5
    enabled: bool = True
    backfill: float = 4
    min_speech: float = 3.0


def make_wav(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    return output.getvalue()


class Segmenter:
    def __init__(self, settings, vad_model="silero"):
        self.settings = settings
        self.fsmn = None
        if settings.enabled and vad_model == "fsmn":
            from .fsmn_vad import FsmnVad

            self.fsmn = FsmnVad()
        elif settings.enabled:
            from faster_whisper.vad import VadOptions, get_vad_model

            # Warm up the cached model here so parallel jobs share one ONNX session.
            get_vad_model()
            self.options = VadOptions(
                threshold=settings.vad_threshold,
                min_silence_duration_ms=64,
                speech_pad_ms=0,
                min_speech_duration_ms=96,
            )

    @property
    def planning_margin(self):
        return self.settings.max_speech if self.settings.enabled else 0

    def spans(self, wav, *, focus=None):
        return list(self.iter_spans(wav, focus=focus))

    def iter_spans(self, wav, *, focus=None):
        with wave.open(io.BytesIO(wav), "rb") as audio:
            pcm = audio.readframes(audio.getnframes())
        if not pcm:
            return
        planned = self._plan(pcm)
        if focus is not None:
            sample = focus * SAMPLE_RATE
            planned.sort(key=lambda span: (max(span[0] - sample, sample - span[1], 0), sample >= span[1]))
        for start, end in planned:
            yield start / SAMPLE_RATE, make_wav(pcm[start * 2:end * 2])

    def _plan(self, pcm):
        maximum = max(1, round(self.settings.max_speech * SAMPLE_RATE))
        if self.settings.enabled:
            import numpy as np

            waveform = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
            if self.fsmn is not None:
                ranges = self.fsmn.ranges(waveform, replace(self.settings, min_silence_ms=64, pad_ms=0))
            else:
                from faster_whisper.vad import get_speech_timestamps

                ranges = get_speech_timestamps(waveform, self.options)
            return plan_spans(pcm, ((item["start"], item["end"]) for item in ranges),
                              minimum=round(self.settings.min_speech * SAMPLE_RATE), maximum=maximum,
                              preferred_pause=self.settings.min_silence_ms * SAMPLE_RATE // 1000,
                              padding=self.settings.pad_ms * SAMPLE_RATE // 1000)
        total = len(pcm) // 2
        return [(start, min(start + maximum, total)) for start in range(0, total, maximum)]
