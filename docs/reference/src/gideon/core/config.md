# `src/gideon/core/config.py`

**Every tunable in the system, in one dataclass.** No module reads an environment
variable or hardcodes a path of its own; they take a `Config` or a value off one.

## Resolution order

`Config.load()` reads the **first file that exists** and stops:

1. `$GIDEON_CONFIG` (set by `scripts/run-local.sh` to `packaging/config/config.toml`)
2. `~/.config/gideon/config.toml`
3. `/etc/gideon/config.toml` (shipped by the .deb, marked as a dpkg conffile)

**First file wins entirely — there is no merging.** A user file that sets one key does
not inherit the rest from `/etc`; it inherits the dataclass defaults. Both top-level keys
and one level of TOML sections are flattened onto the dataclass; unknown keys are dropped
silently.

## Model paths

Derived, never configured directly, from two environment variables the launcher sets:

| Property | Resolves to |
|---|---|
| `voice_path` | `$GIDEON_MODELS/piper/<voice>.onnx` |
| `vad_path` | `$GIDEON_MODELS/vad/silero_vad.onnx` |
| `whisper_dir` | `$GIDEON_MODELS/whisper/<whisper_model>/` |

`GIDEON_MODELS` defaults to `$GIDEON_HOME/models`; `GIDEON_HOME` defaults to `/opt/gideon`.

## Groups of settings

| Group | Keys |
|---|---|
| audio | `sample_rate` 16000, `frame` 512 (fixed by Silero v4), `input_device`, `output_device` |
| endpointing | `vad_threshold`, `speech_start_frames`, `silence_end_ms`, `max_segment_s`, `pre_roll_ms` |
| stt | `whisper_model` `tiny.en`, `whisper_compute` `int8`, `whisper_threads` |
| wake | `wake_phrases`, `wake_fuzz` 0.80 |
| conversation | `followup_window_s` 8.0, `control_socket` true, `hotkey_window_s` 10.0 |
| llm | `llm_enabled`, `llm_url`, `llm_model` `llama3.2:1b`, `llm_timeout` |
| tts | `voice`, `speak_greeting_on_start` |
| logging | `log_level` |

## Two comments that are load-bearing

- **`wake_phrases`.** Whisper renders "Gideon" as "get in" at *every* model size — the name
  collapses onto a common English phrase. The phonetic variants are the fix and must not be
  trimmed to the ones that look correct. Every variant requires a `hey`/`hi` prefix; bare
  "get in" would fire on ordinary speech.
- **`llm_model`.** Must be non-reasoning. Measured on an i7-1165G7: `llama3.2:1b` averages
  0.5 s simple / 1.7 s hard; `3b` costs 2.0 s / 4.3 s for the same correct answers;
  `qwen3`/`deepseek-r1` spend the whole budget thinking (15–22 s).

| | |
|---|---|
| Imports | stdlib only (`os`, `tomllib`, `dataclasses`, `pathlib`) |
| Imported by | `__main__`, `cli.setup` |
| See also | `packaging/config/config.toml` (the shipped defaults) |
