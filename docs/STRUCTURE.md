# Repository structure

One directory per concern, one document per file. Nothing at the repository root except
the two entry-point documents and the four top-level directories.

```
Gideon/
├── README.md                       Install and usage
├── CLAUDE.md                       Working notes for Claude Code
│
├── src/gideon/                     The application (~470 lines)
│   ├── __init__.py                 Version only
│   ├── __main__.py                 Daemon: CLI, endpointing, the pipeline loop
│   ├── core/
│   │   ├── config.py               Every tunable; TOML resolution; model paths
│   │   ├── state.py                Pipeline state + per-subsystem health
│   │   └── credentials.py          API keys, 0600, separate from the config
│   ├── audio/
│   │   └── capture.py              Microphone → bounded frame queue
│   ├── speech/
│   │   ├── vad.py                  Silero v4 voice-activity detection
│   │   ├── stt.py                  faster-whisper speech to text
│   │   ├── tts.py                  Piper text to speech + playback
│   │   └── speaker.py              ECAPA-TDNN: is this the enrolled voice?
│   ├── nlu/
│   │   ├── wake.py                 Wake-phrase matching over the transcript
│   │   └── brain.py                Tier 0/1/2 reply router
│   ├── llm/
│   │   ├── client.py               Ollama HTTP client (Tier 1, optional)
│   │   ├── provider.py             Cloud provider table (Cerebras, OpenRouter)
│   │   ├── cloud.py                OpenAI-compatible cloud client
│   │   └── fallback.py             Cloud first, local second
│   ├── ipc/
│   │   └── control.py              Unix socket: arms push-to-talk, publishes status
│   ├── cli/
│   │   ├── setup.py                `gideon --setup` / `--setup-key`
│   │   ├── enroll.py               `gideon --enroll` — records the owner's voiceprint
│   │   ├── provider.py             `gideon --provider` — picks the Tier 1 brain
│   │   └── ui.py                   `gideon --ui` — execs the indicator
│   ├── ui/                         Tray indicator — SYSTEM python, never imported
│   │   ├── feed.py                 Subscribes to the daemon; reconnects; decides "offline"
│   │   ├── theme.py                One palette and wording; draws the icons
│   │   ├── bubble.py               One chat bubble; the entry/stream animations
│   │   ├── hud.py                  On-screen overlay: the chat thread and the state
│   │   ├── panel.py                Health panel: one row per subsystem
│   │   └── tray.py                 The indicator itself (entry point)
│   └── hotkey/                     evdev key listener — SYSTEM python, never imported
│       ├── device.py               Resolve a device by name; permission diagnostics
│       ├── listener.py             Grab the key, re-inject the rest, signal the daemon
│       ├── discover_devices.py     Manual setup step 1: list input devices
│       ├── confirm_keycode.py      Manual setup step 2: identify the key
│       └── list_keyboards.py       Machine-readable menu source for `--setup-key`
│
├── scripts/                        Everything you run from a shell
│   ├── build-deb.sh                Builds the self-contained .deb
│   └── run-local.sh                Runs the working copy, no install
│
├── packaging/                      Everything that ends up on a user's disk
│   ├── config/config.toml          → /etc/gideon/config.toml
│   ├── launcher/gideon.launcher    → /usr/bin/gideon
│   ├── systemd/gideon.service      → /usr/lib/systemd/user/gideon.service
│   └── debian/                     control, conffiles, postinst, prerm
│
├── requirements/                   Declared dependencies (see docs/DEPENDENCIES.md)
│   ├── python-runtime.txt          Direct Python deps — READ BY THE BUILD
│   ├── python-locked.txt           The resolved closure actually shipped
│   ├── python-optional.txt         Deliberately excluded, with reasons
│   ├── system-apt.txt              Mirrors debian/control Depends:
│   └── build-tools.txt             Needed to build, not to run
│
├── docs/
│   ├── README.md                   Documentation index — start here
│   ├── STRUCTURE.md                This file
│   ├── ARCHITECTURE.md             How the pipeline works, end to end
│   ├── DEPENDENCIES.md             Every dependency, and who installs it
│   ├── PLAN.md                     Design rationale, roadmap, measured corrections
│   ├── HOTKEY.md                   Push-to-talk design and setup
│   ├── NEW-SYSTEM-SETUP.md         Installing on a fresh machine
│   └── reference/                  One document per source file, mirroring the tree
│
└── build/                          Generated. Not source. Safe to delete.
    ├── stage/                      The exact filesystem the .deb installs
    └── gideon_0.1.0_amd64.deb
```

## Why these boundaries

| Directory | Owns | Rule |
|---|---|---|
| `core/` | configuration | the only place that reads env vars or TOML; everything else takes values |
| `audio/` | device I/O | the only place that opens an **input** device |
| `speech/` | the three models | each file wraps exactly one model and knows nothing of the pipeline |
| `nlu/` | interpretation | pure functions and rules; no I/O, no models |
| `llm/` | the optional brain | may fail freely — its absence must cost nothing |
| `ipc/` | out-of-band signals | one socket: the arm bit in, the status feed out |
| `cli/` | user-facing flows | interactive, allowed to shell out |
| `hotkey/` | keyboard | **the boundary**: runs on the system python, imports nothing from `gideon` |
| `ui/` | the desktop face | **the same boundary**: GTK is apt, so these are executed, never imported |

`__main__.py` is the only file that knows the full order of operations. Every module below
it can be read alone.

## The two boundaries that are not stylistic

1. **`hotkey/` and `ui/` never import `gideon`.** `python3-evdev` and PyGObject/GTK are apt
   packages outside the vendored runtime, so those modules are *executed* by
   `/usr/bin/python3`, never imported. That is why `hotkey/listener.py` **and**
   `ui/feed.py` each re-implement the control-socket path instead of importing
   `ipc/control.py`, and why `ui/feed.py` re-states the state names from `core/state.py` —
   change one, change both. `cli/setup.py` and `cli/ui.py` are the bridges: they *exec*
   these scripts, never import them.
2. **`scripts/` vs `packaging/`.** `scripts/` is what a developer runs; `packaging/` is what
   a user ends up with. A file belongs in exactly one.

## Adding a file

1. Put it in the directory that owns the concern; create a new one if none does.
2. Add a matching document under `docs/reference/`, mirroring the path.
3. Link it from `docs/reference/README.md`.
4. If it adds a dependency, update the matching manifest in `requirements/` (see
   §8 of `docs/DEPENDENCIES.md`).
5. If it introduces an invariant, assert it in `--selftest` — that is the test suite.
