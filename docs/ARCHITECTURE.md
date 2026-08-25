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

```
Gideon/
├── README.md                  Install + usage
├── run-local.sh               Run from source, no install, no sudo
├── docs/
│   ├── PLAN.md                Architecture rationale, roadmap, measured corrections
│   └── ARCHITECTURE.md        This file
├── src/gideon/                The application (~470 lines total)
│   ├── __main__.py            Entry point, event loop, follow-up window
│   ├── config.py              Settings dataclass + TOML loading
│   ├── audio.py               Microphone capture
│   ├── vad.py                 Silero voice-activity detection
│   ├── stt.py                 Speech to text
│   ├── wake.py                Wake-phrase matching
│   ├── brain.py               Tier 0/1 router
│   ├── llm.py                 Ollama client (Tier 1)
│   └── tts.py                 Text to speech
├── packaging/
│   ├── build-deb.sh           Builds the self-contained .deb
│   ├── config.toml            Shipped defaults → /etc/gideon/config.toml
│   ├── gideon.launcher        → /usr/bin/gideon
│   ├── gideon.service         systemd *user* unit
│   └── debian/                control, postinst, prerm, conffiles
└── build/                     Generated. Not source. Safe to delete.
    ├── stage/                 Exact filesystem the .deb installs
    └── gideon_0.1.0_amd64.deb The package
```

---

## 3. Source files

### `src/gideon/__main__.py` (167 lines) — entry point and event loop
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

### `src/gideon/config.py` (98 lines) — settings
A single `Config` dataclass holding every tunable, loaded from the first TOML file
found in: `$GIDEON_CONFIG` → `~/.config/gideon/config.toml` → `/etc/gideon/config.toml`.
TOML sections are flattened, so `[llm] llm_model = …` and a top-level `llm_model`
both work. Also resolves model paths relative to `$GIDEON_HOME`.

### `src/gideon/audio.py` (47 lines) — microphone
Opens a `sounddevice` input stream and pushes fixed-size frames onto a **bounded**
queue. If the consumer stalls, frames are dropped rather than blocking the audio
callback — a blocked callback causes clicks and drift. Exposes `muted`, a
`threading.Event` set during playback to break the feedback loop.

### `src/gideon/vad.py` (29 lines) — voice activity detection
Wraps Silero VAD v4 as a streaming classifier. Returns a speech probability per
512-sample frame and carries the LSTM hidden state (`h`, `c`) between calls.
Pinned to **v4**, whose signature is `input/sr/h/c`; v5 uses a single `state`
tensor and is **not** interchangeable.

### `src/gideon/stt.py` (25 lines) — speech to text
`faster-whisper` on CPU, `int8`, 4 threads. Runs with `vad_filter=False` because
`segments()` already did the endpointing, and `condition_on_previous_text=False`
so one utterance cannot contaminate the next.

### `src/gideon/wake.py` (33 lines) — wake phrase
Normalises the transcript, then compares its first *n* words against each configured
phrase, exactly or by `difflib` ratio ≥ `wake_fuzz`. Returns `(matched, remainder)`
so "hey gideon what time is it" yields the query `"what time is it"`.

This matches **transcribed text**, not audio. See §6 for why, and for the "get in"
problem that makes the variant list load-bearing.

### `src/gideon/brain.py` (50 lines) — router
```
Tier 0  rules      greetings, acknowledgements        <1 ms
Tier 1  llm.py     everything else                    ~0.5 s
Tier 2  —          Claude Code headless (not wired)
```
Greetings deliberately never reach the model: "hey gideon" → "Yes?" should not cost
half a second. If Tier 1 is unavailable it says so honestly rather than pretending.

### `src/gideon/llm.py` (119 lines) — Ollama client
Speaks Ollama's HTTP API using `urllib`, so it adds **no dependency** to the package.

- `available()` probes `/api/tags`, caches the result, and warns if the configured
  model is not pulled.
- `ask()` posts to `/api/chat` with a system prompt constraining replies to two
  spoken sentences, and keeps the last 3 turns for follow-up context.
- Failure is never fatal: no Ollama, wrong model, timeout or bad JSON all return
  `None`, and the caller falls back to canned replies.
- Strips `<think>` blocks and detects reasoning models that return only thinking.

### `src/gideon/tts.py` (30 lines) — text to speech
Piper synthesises to an in-memory WAV, which is decoded to PCM and played through
`sounddevice`. Synthesis and playback are separate so `--selftest` can verify
synthesis on a machine with no sound card.

---

## 4. Packaging files

| File | Purpose |
|---|---|
| `build-deb.sh` | Vendors CPython, installs deps, downloads models, strips binaries, builds the `.deb`. Env: `VERSION`, `WHISPER_MODEL`, `VOICE`. |
| `debian/control` | Package metadata and the apt `Depends` line. |
| `debian/postinst` | Verifies the vendored runtime, runs `systemctl --global enable`, prints next steps. |
| `debian/prerm` | Disables and stops the service before removal. |
| `debian/conffiles` | Marks `/etc/gideon/config.toml` as config, so **your edits survive upgrades**. |
| `gideon.launcher` | Becomes `/usr/bin/gideon`. Runs the vendored Python with `-E -s` and injects `sys.path` explicitly. |
| `gideon.service` | systemd **user** unit — it needs your session's audio devices, so it must not be a system unit. |
| `config.toml` | Shipped defaults, installed to `/etc/gideon/config.toml`. |

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

### 5a. System packages (apt) — installed automatically by the `.deb`

| Package | Why |
|---|---|
| `libc6 (≥2.35)` | C runtime. The floor is what makes 24.04 the minimum Ubuntu. |
| `libstdc++6` | C++ runtime for onnxruntime and ctranslate2. |
| `libgomp1` | OpenMP — the multi-threading that makes CPU inference fast. |
| `libportaudio2` | **The microphone and speakers.** `sounddevice` dlopen's it at runtime. The one library not vendored, because audio must use the system's own stack. |
| `libsndfile1` | Audio file decoding used by the audio stack. |
| *Recommends:* `pipewire`, `pipewire-pulse`, `wireplumber` | Ubuntu's audio server. Already present on any normal desktop. |

### 5b. Python packages — bundled inside the `.deb`, nothing to install

**Core — the four things that actually do the work**

| Package | Size | Role |
|---|---|---|
| `faster-whisper` 1.2.1 | 2 MB | Speech to text. A reimplementation of OpenAI Whisper that is ~4× faster and lower-memory. |
| `ctranslate2` 4.8.1 | 70 MB | The inference engine faster-whisper runs on. Provides the `int8` quantisation that makes CPU transcription viable. |
| `onnxruntime` 1.29.0 | 61 MB | Runs the two ONNX models: Silero VAD and the Piper voice. |
| `piper-tts` 1.7.0 | 46 MB | Text to speech, including a bundled espeak-ng for phonemisation. |

**Support**

| Package | Size | Role |
|---|---|---|
| `numpy` 2.5.2 | 58 MB | Every audio buffer is a numpy array. |
| `sounddevice` 0.5.6 | <1 MB | Thin binding to PortAudio; the actual mic/speaker I/O. |
| `av` 18.1.0 | 77 MB | PyAV/ffmpeg bindings. **Unused at runtime** — Gideon passes numpy arrays directly — but `faster_whisper/audio.py` imports it unconditionally, so it cannot be removed. |
| `tokenizers` 0.23.1 | 8 MB | Whisper's text tokenizer. |
| `huggingface-hub` 1.28.0 | 4 MB | Used at **build** time to download the Whisper model. Offline at runtime. |
| `httpx`, `httpcore`, `h11`, `anyio`, `certifi`, `idna` | ~5 MB | Transitive HTTP stack under huggingface-hub. |
| `pyyaml`, `filelock`, `fsspec`, `tqdm`, `packaging`, `protobuf`, `flatbuffers`, `cffi`, `pycparser`, `click`, `setuptools`, `typing-extensions`, `pathvalidate` | ~10 MB | Transitive dependencies. |

**Deliberately excluded:** `openwakeword` (and with it `scipy` + `sklearn`, ~126 MB).
v0.1 does not use it — see §6.

**Not a Python dependency at all:** Ollama. Gideon talks to it over HTTP with
`urllib` from the standard library, which is why the LLM is fully optional.

### 5c. Models — bundled, no download at first run

| Model | Size | Role |
|---|---|---|
| `faster-whisper tiny.en` | 75 MB | Speech recognition, English-only. |
| `piper en_US-lessac-medium` | 61 MB | The voice you hear. |
| `silero_vad.onnx` (v4) | 1.8 MB | Decides which frames contain speech. |

### 5d. Optional — the Tier 1 brain

| Component | Install | Role |
|---|---|---|
| **Ollama** | `curl -fsSL https://ollama.com/install.sh \| sh` | Serves the LLM on `127.0.0.1:11434`. Registers its own systemd service; you never run `ollama serve` by hand. |
| **`llama3.2:1b`** | `ollama pull llama3.2:1b` | The model. 1.3 GB. |

Without these Gideon still runs, answers greetings, and tells you plainly that it
cannot do more.

**Use a non-reasoning model.** `qwen3` and `deepseek-r1` spend their entire token
budget on chain-of-thought before answering — 15–22 s per reply on this CPU, versus
0.5 s for `llama3.2:1b`. Measured here:

| Model | Simple questions | Harder questions |
|---|---|---|
| `llama3.2:1b` *(default)* | 0.53 s | 1.71 s |
| `llama3.2:3b` | 2.02 s | 4.25 s |
| `qwen3:4b` | 15–22 s, often no answer at all | — |

### 5e. Build-time only

| Tool | Role |
|---|---|
| `uv` | Fetches the relocatable CPython and resolves the wheels. |
| `curl`, `sha256sum` | Fetch and verify Silero VAD. |
| `dpkg-deb`, `fakeroot` | Build the package. |
| `strip` (binutils) | Removes debug symbols — saves ~70 MB. |

### Installed size

| Component | Size |
|---|---|
| Python dependencies | 337 MB |
| Vendored CPython 3.12 | 95 MB |
| Models | 137 MB |
| Application | 116 KB |
| **Total installed** | **563 MB** (245 MB compressed) |

---

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
