"""Piper text-to-speech with direct PipeWire/ALSA playback."""
from __future__ import annotations
import io, logging, wave
import numpy as np

log = logging.getLogger("gideon.tts")


class TTS:
    def __init__(self, voice_path, output_device=None):
        from piper import PiperVoice
        log.info("loading piper voice %s", voice_path)
        self._v = PiperVoice.load(str(voice_path))
        self._device = output_device

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self._v.synthesize_wav(text, w)
        buf.seek(0)
        with wave.open(buf) as w:
            sr = w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return pcm, sr

    def say(self, text: str) -> None:
        import sounddevice as sd
        pcm, sr = self.synth(text)
        log.info("say: %s", text)
        sd.play(pcm, sr, device=self._device, blocking=True)
