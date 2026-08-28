"""Speech-to-text via faster-whisper, CPU int8.

Whisper is decoded with a prompt and a hotword biasing it toward "Gideon". The
name is rare enough that the decoder's language model rewrites it to a commoner
phrase ("get in"); both levers raise its prior. They do not fix the problem on
their own - nlu/wake.py still matches phonetically - but they cost nothing at
inference time and remove a share of the mishearings at the source.
"""
from __future__ import annotations
import logging
import numpy as np

log = logging.getLogger("gideon.stt")

# Seeds the decoder's context so "Gideon" is already in play as a token.
PROMPT = "Hey Gideon."
# Weights the name during decoding. faster-whisper ignores this on models that
# do not support it, so it is safe to pass unconditionally.
HOTWORDS = "Gideon"


class STT:
    def __init__(self, model_dir, compute_type="int8", threads=4,
                 prompt=PROMPT, hotwords=HOTWORDS):
        from faster_whisper import WhisperModel
        log.info("loading whisper from %s", model_dir)
        self._m = WhisperModel(str(model_dir), device="cpu",
                               compute_type=compute_type, cpu_threads=threads)
        self._prompt = prompt or None
        self._hotwords = hotwords or None

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self._m.transcribe(
            audio.astype(np.float32), language="en", beam_size=1,
            vad_filter=False, condition_on_previous_text=False,
            no_speech_threshold=0.6,
            initial_prompt=self._prompt, hotwords=self._hotwords,
        )
        return "".join(s.text for s in segments).strip()

    def warm(self) -> None:
        self.transcribe(np.zeros(16000, dtype=np.float32))
