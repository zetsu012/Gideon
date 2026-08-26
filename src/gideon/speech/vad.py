"""Silero VAD (v4, h/c LSTM state) wrapped as a streaming frame classifier."""
from __future__ import annotations
import numpy as np
import onnxruntime as ort


class VAD:
    def __init__(self, model_path, sample_rate: int = 16000):
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        self._s = ort.InferenceSession(str(model_path), sess_options=opts,
                                       providers=["CPUExecutionProvider"])
        self._sr = np.array(sample_rate, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        """frame: float32 mono in [-1, 1], length 512. Returns speech probability."""
        out = self._s.run(None, {
            "input": frame.reshape(1, -1).astype(np.float32),
            "sr": self._sr, "h": self._h, "c": self._c,
        })
        self._h, self._c = out[1], out[2]
        return float(out[0][0][0])
