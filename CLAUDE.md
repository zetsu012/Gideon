# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Gideon: an always-on, fully offline voice assistant for Ubuntu (~470 lines of Python in
`src/gideon/`). Wake detection, STT and TTS all run locally on CPU. v0.1 is a proof of
concept with no tool/command execution.

Deep references: `docs/README.md` (index), `docs/STRUCTURE.md` (folder layout and its
rules), `docs/ARCHITECTURE.md` (the pipeline end to end), `docs/DEPENDENCIES.md` (every
dependency and who installs it), `docs/reference/` (**one page per file**),
`docs/PLAN.md` (design rationale, roadmap, measured corrections), `README.md` (usage).

**When you add or move a file, mirror it in `docs/reference/` and link it from
`docs/reference/README.md`; when you add a dependency, update `requirements/`.**

## Commands

```bash
sudo apt install libportaudio2      # once; the only library not vendored
./scripts/build-deb.sh              # once; stages runtime + models into build/stage/
./scripts/run-local.sh              # run the working copy in src/
./scripts/run-local.sh --selftest   # load and verify all models; works without PortAudio
./scripts/run-local.sh --say "hi"   # speaker smoke test
./scripts/run-local.sh --once -v    # handle one utterance, verbose transcript logging
./scripts/run-local.sh --setup      # interactive: check install, start daemon, offer key setup
./scripts/run-local.sh --setup-key  # interactive: wire up the push-to-talk key only
./scripts/run-local.sh --ui         # tray icon + HUD + health panel (needs GTK from apt)
./scripts/run-local.sh --ui --health # one-shot text health report; exit 1 if offline
```

`scripts/run-local.sh` reuses the staged runtime/models but puts `src/` first on `sys.path`, so
edits take effect on the next run with **no rebuild**. Only re-run `build-deb.sh` when
dependencies or models change (`VERSION=`, `WHISPER_MODEL=` env overrides; needs `uv`,
`curl`, `dpkg-deb`, `fakeroot`).

There is no test suite. `--selftest` is the check: it loads every model and asserts wake
matching, the Tier 0 router and TTS synthesis. Add new invariants there. Installed
behaviour is inspected via `systemctl --user {start,restart} gideon` and
`journalctl --user -u gideon -f`.

## Architecture

Single-threaded pipeline in `__main__.py`, one package per concern
(`core/ audio/ speech/ nlu/ llm/ ipc/ cli/ hotkey/ ui/` — see `docs/STRUCTURE.md`):

`audio/capture.py` (callback thread → bounded queue, 16 kHz float32 512-sample frames)
→ `speech/vad.py` (Silero v4 ONNX, per-frame speech probability)
→ `__main__.segments()` (turns frame probabilities into whole utterances)
→ `speech/stt.py` (faster-whisper) → `nlu/wake.py` (fuzzy transcript match)
→ `nlu/brain.py` (router) → `llm/client.py` (Ollama over HTTP, optional)
→ `speech/tts.py` (Piper) → speakers.
`ipc/control.py` sits beside that pipeline: a unix-socket thread that lets an outside
process arm the daemon (see "Push-to-talk" below) and streams `core/state.py`'s
`StatusBus` to the tray indicator in `ui/` (see "The indicator" below).

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
- **Push-to-talk coexists with the wake phrase.** `ipc/control.py` binds
  `$XDG_RUNTIME_DIR/gideon.sock`; a `wake` line arms `Control` for
  `hotkey_window_s`, and the main loop's `ctrl.consume()` makes the next utterance a
  query (logged `KEY`). It reuses the follow-up path rather than adding a second
  one. The point is that a key press must NOT start a second Gideon - the daemon
  owns the microphone. `gideon/hotkey/` holds the evdev listener that sends it.
  Those modules are EXECUTED by `/usr/bin/python3`, never imported: evdev is an apt
  package, not part of the vendored runtime, so they import nothing from `gideon`
  and re-implement the socket path rather than sharing it. `cli/setup.py` (`gideon
  --setup` / `--setup-key`) shells out to them; it is the only user-facing setup
  path — there is no shell script. `gideon.service` needs `ReadWritePaths=%t` for the
  socket to bind under `ProtectSystem=strict`.
- **The indicator is the daemon's only window.** `core/state.py` holds a `StatusBus` -
  pipeline state (`idle`/`listening`/`thinking`/`speaking`/`followup`) plus one health entry
  per subsystem - that `__main__.py` stamps at each transition and `ipc/control.py` streams
  over `subscribe`. `gideon/ui/` (tray icon, on-screen HUD, health panel) is a pure view of
  it: every health row is a fact the daemon published or something the UI just measured,
  never a constant. Rules that matter: publish a window's deadline BEFORE the state that
  depends on it, or the bus ticker expires it instantly; the fan-out is non-blocking and
  drops updates, because nothing may stall the mic; `Control.start()` pings before unlinking
  an existing socket, so a second instance cannot steal it from the daemon that owns the
  microphone. `--selftest` binds a scratch path for the same reason.
- **`ui/` follows the `hotkey/` rule.** GTK and PyGObject are apt packages, not vendored, so
  `ui/*.py` are EXECUTED by `/usr/bin/python3` and import nothing from `gideon` - they
  re-state the socket path and the state names instead. `cli/ui.py` (`gideon --ui`) is the
  bridge. GTK **3**, not 4: the AppIndicator library links GTK 3 and the two cannot share a
  process. The HUD re-execs onto XWayland because Mutter has no layer-shell, so a
  Wayland-native window cannot be placed or kept on top.
- **Config resolution.** `Config.load()` reads the first existing of `$GIDEON_CONFIG`,
  `~/.config/gideon/config.toml`, `/etc/gideon/config.toml` — first file wins entirely, no
  merging. Both top-level and one level of TOML sections are flattened onto the dataclass;
  unknown keys are silently dropped. Model paths derive from `GIDEON_HOME`/`GIDEON_MODELS`.

## Layout

`src/gideon/` is one package per concern: `core/` (config, state), `audio/` (capture),
`speech/` (vad, stt, tts), `nlu/` (wake, brain), `llm/` (client), `ipc/` (control),
`cli/` (setup, ui), `hotkey/` (system-python evdev scripts), `ui/` (system-python GTK
indicator). `scripts/` is what a developer
runs, `packaging/` is what a user ends up with, `requirements/` declares dependencies.
Full rules in `docs/STRUCTURE.md`.

## Packaging

`scripts/build-deb.sh` produces a self-contained `.deb`: a vendored relocatable CPython, the resolved
dependency closure, and all models baked in, so installation needs only apt and first run
needs no network. The launcher runs Python with `-E -s` so a stray `PYTHONPATH` or
`~/.local` site-packages can never shadow the vendored numpy/onnxruntime — which is why
`sys.path` is injected explicitly in `packaging/launcher/gideon.launcher` and in
`scripts/run-local.sh`.
Runs as a systemd **user** unit, not system-wide. The Silero VAD download is SHA-pinned to
v4 (the h/c LSTM-state interface `speech/vad.py` implements) and the build aborts on mismatch.
`build/` is generated, gitignored, and safe to delete.

Direct Python dependencies live in `requirements/python-runtime.txt`, which the build
**reads** — add a dependency there, not in the script. The shipped closure is recorded in
`requirements/python-locked.txt`; apt deps mirror `packaging/debian/control` in
`requirements/system-apt.txt`. See `docs/DEPENDENCIES.md`.
