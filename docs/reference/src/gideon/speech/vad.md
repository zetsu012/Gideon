# `src/gideon/speech/vad.py`

**Silero VAD v4 as a streaming frame classifier.** `VAD(model_path, sample_rate)` is
callable: give it one 512-sample float32 frame, get back a speech probability in `[0, 1]`.

## Why v4 specifically

This wrapper implements the **h/c LSTM-state interface**: it feeds `input`, `sr`, `h`, `c`
and reads the two updated states back out of the model outputs. Silero v5 replaced that
with a single fused `state` tensor, so a v5 file does not just behave differently — it
fails to run against this code. `scripts/build-deb.sh` therefore downloads the v4 file
from a pinned upstream tag and **aborts the build on a SHA-256 mismatch**.

## Session tuning

`inter_op_num_threads = 1`, `intra_op_num_threads = 1`, CPU provider only. The model is
tiny and runs ~31 times a second; thread pools would cost more than they save, and the
cores are wanted by Whisper. `log_severity_level = 3` silences onnxruntime's startup noise.

## State

`reset()` zeroes the two `(2, 1, 64)` LSTM states. `__main__.segments()` calls it after
every completed utterance, so one long sentence cannot bias detection of the next.

| | |
|---|---|
| Imports | `numpy`, `onnxruntime` |
| Imported by | `__main__` |
| Model | `$GIDEON_MODELS/vad/silero_vad.onnx` (~1.8 MB) |
