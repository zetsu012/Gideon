# `src/gideon/__main__.py`

**The daemon.** Argument parsing, the endpointing generator, and the single-threaded
pipeline loop that wires every other module together. This is the only file that knows
the full order of operations; each subpackage below it knows only its own stage.

## Entry points

| Flag | Behaviour |
|---|---|
| *(none)* | run forever: listen, wake, answer |
| `--once` | handle exactly one utterance, then exit (what the hotkey falls back to) |
| `--say TEXT` | load TTS only, speak, exit — speaker smoke test |
| `--selftest` | load every model, assert the invariants below, exit. Works without PortAudio |
| `--setup` | hand off to `gideon.cli.setup.setup()` |
| `--setup-key` | hand off to `gideon.cli.setup.setup_key()` |
| `-v/--verbose` | DEBUG logging, including every rejected transcript |

`--setup`/`--setup-key` are handled **before** the model-existence check: diagnosing a
broken install is what they are for, so a missing model must not block them.

## `segments(mic, vad, cfg)`

Turns per-frame VAD probabilities into whole utterances. State machine:

1. **idle** — frames accumulate in a `pre_roll` ring (`pre_roll_ms`, default 300 ms) so
   the first syllable is not clipped once speech is detected.
2. `speech_start_frames` consecutive voiced frames (~96 ms) open a segment, seeded with
   the pre-roll.
3. **active** — a segment closes on `silence_end_ms` of trailing silence or at
   `max_segment_s`. `vad.reset()` clears the LSTM state between utterances.
4. Segments shorter than 300 ms are dropped as blips.

## The reply loop

```
transcribe → ctrl.consume() → wake.match() → brain.respond() → tts.say()
```

Three ways an utterance becomes a query, logged with a distinct tag:

| Tag | Cause |
|---|---|
| `WAKE` | the transcript head matched a wake phrase |
| `KEY` | the push-to-talk socket was armed while this was being said |
| `FOLLOW` | inside `followup_window_s` after the previous reply |
| `----` | none of the above — heard, ignored. Grep this to debug misses |

Stop words (`stop`, `never mind`, `cancel`, `that's all`, `thanks`) close the window and
call `llm.reset()`.

## Invariants to preserve

- **Self-hearing guard.** Every speaking path is `mic.muted.set()` → speak → `sleep(0.15)`
  → `mic.drain()` → `mic.muted.clear()`. Any new speaking path must repeat it exactly, or
  Gideon transcribes his own voice and answers himself.
- **Push-to-talk reuses the follow-up path** rather than adding a second one.
- `--selftest` is the test suite. New invariants go in that block.

| | |
|---|---|
| Imports | `.core.config`, `.audio.capture`, `.speech.{vad,stt,tts}`, `.nlu.{wake,brain}`, `.ipc.control`, `.llm.client`, lazily `.cli.setup` |
| Imported by | nothing — it is the entry module |
