# Gideon — Codebase and Dependency Reference

Everything in this repository, what each piece is for, and what it depends on.
For the design rationale and roadmap see [PLAN.md](PLAN.md); for install and usage
see [../README.md](../README.md).

---

## 1. What the system does

```
   microphone
       │  16 kHz mono, 512-sample frames (32 ms)
       ▼
  ┌─ audio.py ────────┐  callback thread → bounded queue; mutes itself while speaking
       │
       ▼
  ┌─ vad.py ──────────┐  Silero VAD scores each frame 0..1 for "is this speech"
       │                 __main__.segments() turns that into whole utterances
       ▼
  ┌─ stt.py ──────────┐  faster-whisper transcribes the utterance  (~0.25 s)
       │
       ▼
  ┌─ wake.py ─────────┐  is this "hey gideon"?  (fuzzy, phonetic variants)
       │                 …or are we inside the 8 s follow-up window?
       ▼
  ┌─ brain.py ────────┐  Tier 0 rules → instant   |   Tier 1 llm.py → Ollama (~0.5 s)
       │
       ▼
  ┌─ tts.py ──────────┐  Piper synthesises speech (~0.08 s) and plays it
       ▼
    speakers
```

Total spoken round trip on an i7-1165G7: **≈0.9 s** for an LLM-answered question,
**≈0.35 s** for a Tier 0 greeting.

---

## 2. Repository layout

Full tree, boundaries and the rules for adding a file: **[STRUCTURE.md](STRUCTURE.md)**.
Every file also has its own page under **[reference/](reference/README.md)**. In brief:

```
Gideon/
├── src/gideon/          application      core/ audio/ speech/ nlu/ llm/ ipc/ cli/ hotkey/
├── scripts/             what you run     build-deb.sh, run-local.sh
├── packaging/           what users get   config/ launcher/ systemd/ debian/
├── requirements/        declared deps    python-runtime/locked/optional, system-apt, build-tools
├── docs/                this, plus reference/ — one page per file
└── build/               generated; safe to delete
```

---

## 3. Source files

Summaries. The full page for each file — public surface, invariants, what breaks if you
change it — is under [`reference/src/gideon/`](reference/README.md).

### `src/gideon/__main__.py` (204 lines) — entry point and event loop
Parses arguments, loads models, owns the listening loop.

- `segments()` — converts the VAD's per-frame probabilities into whole utterances.
  Opens a segment after 3 consecutive speech frames, closes it after 700 ms of
  silence, and keeps a 300 ms **pre-roll** so the first syllable is not clipped.
  Discards anything under 300 ms as a blip.
- The main loop decides, per utterance, whether it was addressed to Gideon: either
  it matched the wake phrase, **or** it arrived inside the follow-up window.
- **Follow-up window** — for `followup_window_s` (8 s) after each reply, the wake
  phrase is not required, so a conversation flows. "stop" / "never mind" / "thanks"
  closes it early and clears LLM context.
- Mutes the microphone around playback so Gideon never transcribes his own voice.

Flags: `--selftest` (load and verify everything, no audio device needed), `--say TEXT`,
`--once`, `-v`.

### `src/gideon/core/config.py` (107 lines) — settings
A single `Config` dataclass holding every tunable, loaded from the first TOML file
found in: `$GIDEON_CONFIG` → `~/.config/gideon/config.toml` → `/etc/gideon/config.toml`.
TOML sections are flattened, so `[llm] llm_model = …` and a top-level `llm_model`
both work. Also resolves model paths relative to `$GIDEON_HOME`.

### `src/gideon/audio/capture.py` (47 lines) — microphone
Opens a `sounddevice` input stream and pushes fixed-size frames onto a **bounded**
queue. If the consumer stalls, frames are dropped rather than blocking the audio
callback — a blocked callback causes clicks and drift. Exposes `muted`, a
`threading.Event` set during playback to break the feedback loop.

### `src/gideon/speech/vad.py` (29 lines) — voice activity detection
Wraps Silero VAD v4 as a streaming classifier. Returns a speech probability per
512-sample frame and carries the LSTM hidden state (`h`, `c`) between calls.
Pinned to **v4**, whose signature is `input/sr/h/c`; v5 uses a single `state`
tensor and is **not** interchangeable.

### `src/gideon/speech/stt.py` (25 lines) — speech to text
`faster-whisper` on CPU, `int8`, 4 threads. Runs with `vad_filter=False` because
`segments()` already did the endpointing, and `condition_on_previous_text=False`
so one utterance cannot contaminate the next.

### `src/gideon/nlu/wake.py` (33 lines) — wake phrase
Normalises the transcript, then compares its first *n* words against each configured
phrase, exactly or by `difflib` ratio ≥ `wake_fuzz`. Returns `(matched, remainder)`
so "hey gideon what time is it" yields the query `"what time is it"`.

This matches **transcribed text**, not audio. See §6 for why, and for the "get in"
problem that makes the variant list load-bearing.

### `src/gideon/nlu/brain.py` (50 lines) — router
```
Tier 0  rules      greetings, acknowledgements        <1 ms
Tier 1  llm.py     everything else                    ~0.5 s
Tier 2  —          Claude Code headless (not wired)
```
Greetings deliberately never reach the model: "hey gideon" → "Yes?" should not cost
half a second. If Tier 1 is unavailable it says so honestly rather than pretending.

### `src/gideon/llm/client.py` (119 lines) — Ollama client
Speaks Ollama's HTTP API using `urllib`, so it adds **no dependency** to the package.

- `available()` probes `/api/tags`, caches the result, and warns if the configured
  model is not pulled.
- `ask()` posts to `/api/chat` with a system prompt constraining replies to two
  spoken sentences, and keeps the last 3 turns for follow-up context.
- Failure is never fatal: no Ollama, wrong model, timeout or bad JSON all return
  `None`, and the caller falls back to canned replies.
- Strips `<think>` blocks and detects reasoning models that return only thinking.

### `src/gideon/speech/tts.py` (30 lines) — text to speech
Piper synthesises to an in-memory WAV, which is decoded to PCM and played through
`sounddevice`. Synthesis and playback are separate so `--selftest` can verify
synthesis on a machine with no sound card.

### `src/gideon/ipc/control.py` (125 lines) — push-to-talk socket
A unix socket at `$XDG_RUNTIME_DIR/gideon.sock`. A `wake` line arms the **running**
daemon for `hotkey_window_s`, and the next utterance is treated as a query — the key
press must not start a second Gideon, because the daemon already owns the microphone.
Binding failure is never fatal: the daemon simply has no push-to-talk.

### `src/gideon/cli/setup.py` (305 lines) — interactive setup
`gideon --setup` and `--setup-key`. Checks the install, starts the user daemon, and wires
a keyboard key by shelling out to `hotkey/` under the **system** python. The only
user-facing setup path; there is no shell script.

### `src/gideon/hotkey/` — keyboard listener (system python)
Grabs one key on one keyboard and re-injects the rest through uinput, then signals the
daemon over the control socket. Imports nothing from `gideon`: `python3-evdev` is an apt
package, not part of the vendored runtime. See [HOTKEY.md](HOTKEY.md).

---

## 4. Packaging files

| File | Purpose |
|---|---|
| `scripts/build-deb.sh` | Vendors CPython, installs deps, downloads models, strips binaries, builds the `.deb`. Env: `VERSION`, `WHISPER_MODEL`, `VOICE`. |
| `packaging/debian/control` | Package metadata and the apt `Depends` line. |
| `packaging/debian/postinst` | Verifies the vendored runtime, runs `systemctl --global enable`, prints next steps. |
| `packaging/debian/prerm` | Disables and stops the service before removal. |
| `packaging/debian/conffiles` | Marks `/etc/gideon/config.toml` as config, so **your edits survive upgrades**. |
| `packaging/launcher/gideon.launcher` | Becomes `/usr/bin/gideon`. Runs the vendored Python with `-E -s` and injects `sys.path` explicitly. |
| `packaging/systemd/gideon.service` | systemd **user** unit — it needs your session's audio devices, so it must not be a system unit. |
| `packaging/config/config.toml` | Shipped defaults, installed to `/etc/gideon/config.toml`. |

### Why the package vendors its own Python
Ubuntu 24.04 ships Python 3.12; 26.04 ships 3.14. A package depending on the system
interpreter cannot support both. `build-deb.sh` therefore bundles a relocatable
CPython 3.12, so one `.deb` installs identically on 24.04, 25.04 and 26.04.

Three traps this build works around, all found the hard way:
1. uv's Python directory contains symlinks pointing outside itself — needs `cp -aL`.
2. `python3 -E` discards `PYTHONPATH`, so the launcher sets `sys.path` in code.
3. openWakeWord 0.6 stopped bundling models, so Silero is fetched from its own
   repo at a pinned tag and verified by sha256.

---

## 5. Dependencies

Moved to its own document: **[docs/DEPENDENCIES.md](DEPENDENCIES.md)** — what apt installs,
what is vendored inside the package, the three models, what you install by hand, and what is
deliberately excluded. Machine-readable manifests are in [`requirements/`](../requirements/).

## 6. Design decisions worth knowing

### Wake detection goes through Whisper, not a wake-word model
The conventional design runs a tiny always-on wake-word model and only then wakes
the expensive parts. v0.1 does not, because openWakeWord ships **no "gideon" model**,
and 0.6 stopped bundling models at all. Training one is a separate step.

So Gideon gates on VAD and transcribes every speech segment. The cost is Whisper
running on all speech rather than only after a trigger — 0.25 s per utterance here,
acceptable. The benefit is that it responds to the real phrase from first install.

### "Gideon" is heard as "get in"
Whisper transcribes the name as **"get in"** at *every* model size — `tiny.en`,
`base.en` and `small.en` all make the identical mistake, the larger ones just more
slowly. The name collapses onto a far more common English phrase.

`wake_phrases` therefore carries phonetic variants ("hey get in", "hike it in", …).
**That list is load-bearing** — trimming it to the entries that look correct will
stop the wake phrase working. Every variant keeps a `hey`/`hi` prefix so ordinary
speech ("let me get in the car") does not trigger. Measured: 5/6 recall, 0/6 false
accepts against synthesised speech.

### The GPU is unused
An MX450 has 2 GB of VRAM. Whisper runs faster on CPU here than the transfer
overhead would justify, and Ollama reports the LLM running ~100% on CPU because the
model does not fit. The package therefore ships **no CUDA dependency**, which keeps
it portable to machines with no discrete GPU.

### Failure is never fatal
No Ollama, wrong model, timeout, malformed response — each degrades to a canned
reply. A voice assistant that hangs is worse than one that admits its limits.
