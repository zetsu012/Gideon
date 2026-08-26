# Gideon

An always-on, offline voice assistant for Ubuntu. Say **"hey gideon"** and it answers
out loud. Wake detection, speech recognition and speech synthesis all run locally on
the CPU — no network, no API key, no account, no cost.

**v0.1 is a proof of concept.** It answers greetings from a built-in rule set and
everything else from a local LLM. It has **no tool or command execution** — it cannot
set timers, open apps or control your system yet.

---

## Getting started

### Prerequisites

For the `.deb`: **none.** The package is self-contained — it bundles its own Python
runtime, every Python dependency, and all speech models. `apt` pulls in the handful
of system libraries it needs (`libportaudio2` and friends) automatically. It works
on **Ubuntu 24.04 and later**, and needs no network access after installation.

You only need to install things by hand in two cases:

| If you want to… | Install |
|---|---|
| Run from source instead of the `.deb` | `sudo apt install libportaudio2` |
| Give Gideon a real brain (recommended) | Ollama — see [step 3](#3-give-it-a-brain-optional) |

### 1. Install

```bash
sudo apt install ./gideon_0.1.0_amd64.deb
```

That is the entire installation. It takes about 560 MB.

### 2. Check it works

```bash
gideon --selftest              # loads every model and verifies them
gideon --say "hello there"     # speaker test
```

Then start it:

```bash
systemctl --user start gideon      # start now
journalctl --user -u gideon -f     # watch it listen
```

It starts automatically at every login from now on. Say **"hey gideon"**.

To see that it is running — a tray icon with the live state, an on-screen HUD and a health
panel:

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
systemctl --user enable --now gideon-ui
gideon --ui --health           # or the same thing as text, over ssh
```

See [docs/INDICATOR.md](docs/INDICATOR.md).

### 3. Give it a brain (optional)

Without this, Gideon answers greetings and honestly says it cannot do more.
To get real answers — still free, still local, still no API key:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:1b
systemctl --user restart gideon
```

You do **not** need to run `ollama serve` or `ollama run`. The installer registers a
systemd service that starts on boot; Gideon talks to it over HTTP on port 11434.

> **Use a non-reasoning model.** `qwen3` and `deepseek-r1` spend their whole token
> budget thinking before answering — 15–22 s per reply on a laptop CPU, versus 0.5 s
> for `llama3.2:1b`. `llama3.2:3b` also works and is a little more articulate, but
> is ~2.5× slower.

### 4. Talk to it

After each reply Gideon stays open for **8 seconds**, so a conversation does not need
the wake phrase on every sentence:

```
you:     hey gideon
gideon:  Yes?
you:     what is the capital of France      ← no wake phrase needed
gideon:  The capital of France is Paris.
you:     what is 17 times 23                ← still inside the window
gideon:  The result of 17 times 23 is 391.
```

Say "stop", "never mind" or "thanks" to close the window early. The logs mark every
utterance `WAKE`, `FOLLOW` or `----` (ignored), which is the fastest way to see what
Gideon actually heard.

### Uninstall

```bash
sudo apt remove gideon        # keeps /etc/gideon/config.toml
sudo apt purge gideon         # removes it too
```

---

## Run locally from source

For hacking on it, without installing anything system-wide:

```bash
sudo apt install libportaudio2    # once - the only library not vendored
./scripts/build-deb.sh            # once - stages the runtime and models
./scripts/run-local.sh            # start listening
```

| Command | Does |
|---|---|
| `./scripts/run-local.sh` | Start listening |
| `./scripts/run-local.sh --selftest` | Verify models — works without PortAudio |
| `./scripts/run-local.sh --say "hi"` | Speaker test |
| `./scripts/run-local.sh --once -v` | Handle one utterance, verbose |

`scripts/run-local.sh` reuses the vendored Python and models staged under `build/stage/`,
but puts `src/` first on `sys.path`, so your edits take effect on the next run with
no rebuild. Only re-run `build-deb.sh` when dependencies or models change.

### Build the package

```bash
./scripts/build-deb.sh                          # -> build/gideon_0.1.0_amd64.deb
WHISPER_MODEL=base.en ./scripts/build-deb.sh    # more accurate, slower
VERSION=0.2.0 ./scripts/build-deb.sh
```

Needs `uv`, `curl`, `dpkg-deb` and `fakeroot`. The build bakes the models in, so the
resulting `.deb` installs with no network.

---

## Performance

Measured on a ThinkPad T14 Gen 2i (i7-1165G7), CPU only, no GPU:

| Stage | Time |
|---|---|
| Speech to text (`tiny.en`, int8) | 0.22–0.26 s |
| LLM reply (`llama3.2:1b`) | 0.5 s simple, 1.7 s harder |
| Speech synthesis (Piper) | 0.08 s |
| **Full spoken round trip** | **≈0.9 s** |
| Greeting (Tier 0, no model) | ≈0.35 s |
| Idle | VAD only, ~1 core-% |

---

## Configuration

Defaults live in `/etc/gideon/config.toml`. Override per user in
`~/.config/gideon/config.toml`, then `systemctl --user restart gideon`.
Your edits to `/etc/gideon/config.toml` survive package upgrades.

Commonly changed:

| Setting | Default | Notes |
|---|---|---|
| `llm_model` | `llama3.2:1b` | Must be a non-reasoning model |
| `followup_window_s` | `8.0` | Seconds to keep listening after a reply |
| `wake_fuzz` | `0.80` | Lower = easier to trigger, more false accepts |
| `whisper_model` | `tiny.en` | `base.en` is more accurate, ~1.5× slower |
| `input_device` | auto | Set if the wrong mic is picked |

---

## Troubleshooting

**It never responds.** Run `./scripts/run-local.sh -v` and watch the transcript lines. Every
speech segment is logged with what Whisper heard and whether it matched. If the text
looks nothing like what you said, the problem is recognition, not matching.

**It responds to the wrong things.** Raise `wake_fuzz` toward 0.9.

**It cannot hear you.** Check the right microphone is selected — `wpctl status`, then
set `input_device` in the config.

**Recognition accuracy is mediocre.** `tiny.en` is the smallest Whisper model and is
the accuracy floor. Rebuild with `WHISPER_MODEL=base.en` for a real improvement at
~1.5× the latency. Note this will *not* fix the wake phrase specifically — see below.

**"Gideon" is heard as "get in".** Expected, and handled. Whisper renders the name as
"get in" at *every* model size; `wake_phrases` carries phonetic variants to absorb
this. Do not trim that list to the entries that look correct — it will stop working.

---

## Documentation

Start at **[docs/README.md](docs/README.md)** — the documentation index.

| Document | Contents |
|---|---|
| [docs/STRUCTURE.md](docs/STRUCTURE.md) | Folder layout, where each concern lives, how to add a file |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How a spoken sentence becomes a spoken reply, file by file |
| [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) | Every dependency: vendored, apt-installed, or manual |
| [docs/reference/](docs/reference/README.md) | **One page per file** — purpose, API, invariants |
| [docs/PLAN.md](docs/PLAN.md) | Design rationale, roadmap, and corrections found by measurement |
| [docs/HOTKEY.md](docs/HOTKEY.md) | Push-to-talk: design and setup |
| [docs/INDICATOR.md](docs/INDICATOR.md) | Tray icon, HUD and health panel |
| [docs/NEW-SYSTEM-SETUP.md](docs/NEW-SYSTEM-SETUP.md) | Installing on a fresh machine |

## Roadmap

v0.1's router is shaped for the tiered brain in `docs/PLAN.md`: Tier 0 rule intents
(timers, volume, launching apps), Tier 1 local LLM (**done**), Tier 2 Claude Code
headless for hard questions. A trained wake-word model would replace the
transcript-matching approach.
