# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Gideon: an always-on, fully offline voice assistant for Ubuntu (~470 lines of Python in
`src/gideon/`). Wake detection, STT and TTS all run locally on CPU. v0.1 is a proof of
concept with no tool/command execution. Not a git repository.

Deep references: `docs/ARCHITECTURE.md` (every file + dependency rationale),
`docs/PLAN.md` (design rationale, roadmap, measured corrections), `README.md` (install/usage).

## Commands

```bash
sudo apt install libportaudio2      # once; the only library not vendored
./packaging/build-deb.sh            # once; stages runtime + models into build/stage/
./run-local.sh                      # run the working copy in src/
./run-local.sh --selftest           # load and verify all models; works without PortAudio
./run-local.sh --say "hi"           # speaker smoke test
./run-local.sh --once -v            # handle one utterance, verbose transcript logging
```

`run-local.sh` reuses the staged runtime/models but puts `src/` first on `sys.path`, so
edits take effect on the next run with **no rebuild**. Only re-run `build-deb.sh` when
dependencies or models change (`VERSION=`, `WHISPER_MODEL=` env overrides; needs `uv`,
`curl`, `dpkg-deb`, `fakeroot`).

There is no test suite. `--selftest` is the check: it loads every model and asserts wake
matching, the Tier 0 router and TTS synthesis. Add new invariants there. Installed
behaviour is inspected via `systemctl --user {start,restart} gideon` and
`journalctl --user -u gideon -f`.

## Architecture

Single-threaded pipeline in `__main__.py`, one module per stage:

`audio.py` (callback thread → bounded queue, 16 kHz float32 512-sample frames)
→ `vad.py` (Silero v4 ONNX, per-frame speech probability)
→ `__main__.segments()` (turns frame probabilities into whole utterances)
→ `stt.py` (faster-whisper) → `wake.py` (fuzzy transcript match) → `brain.py` (router)
→ `llm.py` (Ollama over HTTP, optional) → `tts.py` (Piper) → speakers.

Key cross-file behaviours that are not obvious from one file:

- **Wake detection is transcript matching, not a wake-word model.** Whisper runs on every
  VAD-gated segment; `wake.match()` fuzzy-compares the head of the transcript against
  `Config.wake_phrases`. Whisper renders "Gideon" as "get in" at *every* model size — the
  phonetic variants in `wake_phrases` are load-bearing, not padding. Do not trim them to
  the ones that look correct, and do not expect a bigger Whisper model to fix it.
- **Follow-up window.** After a reply, `follow_until` keeps Gideon answering without a wake
  phrase for `followup_window_s` (8 s). Stop words ("stop", "never mind", "thanks") close it
  and reset LLM history. Log lines are tagged `WAKE` / `FOLLOW` / `----` — the fastest way to
  see what was heard and why it did or didn't match.
- **Self-hearing guard.** Before speaking, `mic.muted` is set, then after playback there is a
  0.15 s settle, `mic.drain()`, and unmute. Any new speaking path must keep this sequence.
- **Tiered brain.** Tier 0 = deterministic rules (acks, greetings) so common utterances never
  pay model latency; Tier 1 = local LLM; Tier 2 (Claude Code headless) is an unwired branch in
  `brain.py`. The LLM is strictly optional: a missing/unreachable Ollama probes once, logs
  once, and degrades to canned replies — it must never crash or hang the daemon.
- **Non-reasoning LLM only.** `qwen3`/`deepseek-r1` burn their token budget thinking
  (15–22 s/reply on a laptop CPU vs ~0.5 s for `llama3.2:1b`).
- **Config resolution.** `Config.load()` reads the first existing of `$GIDEON_CONFIG`,
  `~/.config/gideon/config.toml`, `/etc/gideon/config.toml` — first file wins entirely, no
  merging. Both top-level and one level of TOML sections are flattened onto the dataclass;
  unknown keys are silently dropped. Model paths derive from `GIDEON_HOME`/`GIDEON_MODELS`.

## Packaging

`build-deb.sh` produces a self-contained `.deb`: a vendored relocatable CPython, the resolved
dependency closure, and all models baked in, so installation needs only apt and first run
needs no network. The launcher runs Python with `-E -s` so a stray `PYTHONPATH` or
`~/.local` site-packages can never shadow the vendored numpy/onnxruntime — which is why
`sys.path` is injected explicitly in `packaging/gideon.launcher` and in `run-local.sh`.
Runs as a systemd **user** unit, not system-wide. The Silero VAD download is SHA-pinned to
v4 (the h/c LSTM-state interface `vad.py` implements) and the build aborts on mismatch.
`build/` is generated, gitignored, and safe to delete.
