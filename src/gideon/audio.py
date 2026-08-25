"""Microphone capture: fixed-size float32 frames on a bounded queue."""
from __future__ import annotations
import logging, queue, threading
import numpy as np

log = logging.getLogger("gideon.audio")


class Microphone:
    def __init__(self, sample_rate=16000, frame=512, device=None, max_queue=64):
        self.sample_rate, self.frame, self.device = sample_rate, frame, device
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_queue)
        self._stream = None
        # Set while Gideon is speaking, so he never hears his own voice.
        self.muted = threading.Event()

    def _cb(self, indata, frames, time_info, status):
        if status:
            log.debug("stream status: %s", status)
        if self.muted.is_set():
            return
        try:
            self._q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass  # drop rather than block the audio callback

    def __enter__(self):
        import sounddevice as sd
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, blocksize=self.frame, dtype="float32",
            channels=1, device=self.device, callback=self._cb)
        self._stream.start()
        log.info("microphone open @ %d Hz, %d-sample frames", self.sample_rate, self.frame)
        return self

    def __exit__(self, *exc):
        if self._stream:
            self._stream.stop(); self._stream.close()

    def frames(self):
        while True:
            yield self._q.get()

    def drain(self):
        while not self._q.empty():
            try: self._q.get_nowait()
            except queue.Empty: break
