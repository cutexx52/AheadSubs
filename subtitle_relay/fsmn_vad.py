"""Use FunASR's exported FSMN encoder with Relay's offline split settings."""
from pathlib import Path
import re


MODEL = "funasr/fsmn-vad-onnx"
REVISION = "f6e9fbb4cefa7397216c763f21307993f147f585"
SAMPLE_RATE = 16_000
FRAME_SAMPLES = 160
MEL_BINS = 80
STACK = 5


class FsmnVad:
    def __init__(self):
        try:
            import kaldi_native_fbank as knf
        except ImportError as exc:
            raise RuntimeError(
                "FSMN-VAD requires kaldi-native-fbank. Run Prepare dependencies or install .[fsmn-vad]."
            ) from exc
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download

        model = hf_hub_download(MODEL, "model.onnx", revision=REVISION)
        cmvn = Path(hf_hub_download(MODEL, "vad.mvn", revision=REVISION)).read_text(encoding="utf-8")
        # The pinned model's vad.yaml fixes the feature settings and cache shape.
        vectors = re.findall(r"<(?:AddShift|Rescale)>[^[]*\[([^]]+)\]", cmvn)
        self.shift, self.scale = (np.fromstring(vector, sep=" ", dtype=np.float32) for vector in vectors)
        if self.shift.shape != (MEL_BINS * STACK,) or self.scale.shape != self.shift.shape:
            raise ValueError("Unexpected FSMN-VAD normalization dimensions")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])
        self.inputs = [item.name for item in self.session.get_inputs()]
        self.scores = self.session.get_outputs()[0].name
        self.options = knf.FbankOptions()
        self.options.frame_opts.samp_freq = SAMPLE_RATE
        self.options.frame_opts.dither = 0
        self.options.frame_opts.window_type = "hamming"
        self.options.frame_opts.frame_shift_ms = 10
        self.options.frame_opts.frame_length_ms = 25
        self.options.frame_opts.snip_edges = True
        self.options.mel_opts.num_bins = MEL_BINS
        self.options.energy_floor = 0

    def ranges(self, waveform, settings):
        import kaldi_native_fbank as knf
        import numpy as np

        if not waveform.any():
            return []
        fbank = knf.OnlineFbank(self.options)
        fbank.accept_waveform(SAMPLE_RATE, (waveform * 32768).tolist())
        frames = fbank.num_frames_ready
        if not frames:
            return []
        mel = np.asarray([fbank.get_frame(frame) for frame in range(frames)], dtype=np.float32)
        indices = np.arange(frames)[:, None] + np.arange(STACK) - STACK // 2
        stacked = mel[indices.clip(0, frames - 1)].reshape(frames, MEL_BINS * STACK)
        features = ((stacked + self.shift) * self.scale)[None, :, :]
        # A new chunk has independent decoder caches, including during concurrent seeks.
        values = [features, *(np.zeros((1, 128, 19, 1), dtype=np.float32) for _ in self.inputs[1:])]
        scores, = self.session.run([self.scores], dict(zip(self.inputs, values)))
        active = np.flatnonzero(1 - scores[0, :, 0] >= settings.vad_threshold)
        if not active.size:
            return []
        pauses = np.flatnonzero(np.diff(active) - 1 >= settings.min_silence_ms / 10) + 1
        intervals = [(int(block[0]) * FRAME_SAMPLES, (int(block[-1]) + 1) * FRAME_SAMPLES)
                     for block in np.split(active, pauses) if len(block) * 10 >= 160]
        padding = settings.pad_ms * SAMPLE_RATE // 1000
        ranges = []
        for index, (start, end) in enumerate(intervals):
            left = (intervals[index - 1][1] + start) // 2 if index else 0
            right = (intervals[index + 1][0] + end) // 2 if index + 1 < len(intervals) else len(waveform)
            ranges.append({"start": max(left, start - padding), "end": min(right, end + padding)})
        return ranges
