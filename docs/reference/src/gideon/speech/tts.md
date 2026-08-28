# `src/gideon/speech/tts.py`

**Piper text-to-speech with direct playback.**

`TTS(voice_path, output_device=None)` loads the ONNX voice at construction.

- `synth(text) -> (pcm int16, sample_rate)` — Piper writes a WAV into an in-memory
  `io.BytesIO`, which is read straight back as int16 PCM. The WAV round-trip exists because
  `synthesize_wav` is Piper's stable output API; nothing touches disk.
- `say(text)` — `synth()` then `sounddevice.play(..., blocking=True)`.

**`say()` blocks until playback finishes.** The self-hearing guard in `__main__` depends on
that: it mutes the mic, calls `say()`, and only then sleeps 0.15 s and drains. A
non-blocking playback path would break the guard.

Piper's output sample rate (22050 Hz for `en_US-lessac-medium`) is **not** the pipeline's
16 kHz — it is returned alongside the PCM and handed to the device, never assumed.

| | |
|---|---|
| Imports | `numpy`, `wave`, `io`; `piper` and `sounddevice` deferred |
| Imported by | `__main__` |
| Model | `$GIDEON_MODELS/piper/en_US-lessac-medium.onnx` (+ `.json`) |
| External dep | libportaudio2, libsndfile1 |
