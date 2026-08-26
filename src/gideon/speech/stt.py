"""Speech-to-text via faster-whisper, CPU int8."""
from __future__ import annotations
import logging
import numpy as np

log = logging.getLogger("gideon.stt")


class STT:
    def __init__(self, model_dir, compute_type="int8", threads=4):
        from faster_whisper import WhisperModel
        log.info("loading whisper from %s", model_dir)
        self._m = WhisperModel(str(model_dir), device="cpu",
                               compute_type=compute_type, cpu_threads=threads)

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self._m.transcribe(
            audio.astype(np.float32), language="en", beam_size=1,
            vad_filter=False, condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )
        return "".join(s.text for s in segments).strip()

    def warm(self) -> None:
        self.transcribe(np.zeros(16000, dtype=np.float32))
