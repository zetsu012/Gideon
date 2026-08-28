# `src/gideon/audio/capture.py`

**Microphone → bounded queue.** The only file that opens an input device.

`class Microphone(sample_rate=16000, frame=512, device=None, max_queue=64)`, used as a
context manager. `__enter__` imports `sounddevice` (lazily, so `--selftest` runs without
PortAudio), opens a mono float32 `InputStream` and starts it.

## The two rules of the callback

1. **Never block.** PortAudio calls `_cb` from its own realtime thread. On a full queue
   the frame is dropped (`put_nowait` + `except queue.Full: pass`), never awaited.
   64 frames ≈ 2 s of audio; if the pipeline falls that far behind, dropping is correct.
2. **Respect `muted`.** `muted` is a `threading.Event` set by the pipeline while Gideon
   speaks. While set, frames are discarded at the callback, before the queue — that is the
   first half of the self-hearing guard.

`drain()` empties the queue non-destructively-ish (the second half of the guard: it
discards whatever leaked in during the 0.15 s playback tail). `frames()` is an infinite
generator yielding 512-sample `np.ndarray`s.

| | |
|---|---|
| Threads | one PortAudio callback thread, producer; the main thread consumes |
| Imports | `numpy`, `sounddevice` (deferred), stdlib `queue`/`threading` |
| Imported by | `__main__` |
| External dep | **libportaudio2** — `sounddevice` `dlopen()`s it; the one library not vendored |
