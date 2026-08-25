# Gideon — Always-On Local Voice Assistant

**Target:** Lenovo ThinkPad T14 Gen 2i · i7-1165G7 (4C/8T) · 32 GB RAM · MX450 2 GB · Ubuntu 26.04 · Wayland/PipeWire
**Constraints:** zero cost, no API keys, runs entirely on this laptop, always listening.

---

## 1. The hardware constraint that decides everything

| Resource | Reality | Consequence |
|---|---|---|
| MX450, **2 GB VRAM** | Too small for any useful LLM (a 4B model at Q4 needs ~3 GB) | **GPU is for Whisper only.** `faster-whisper small.en` int8_float16 ≈ 600 MB — fits comfortably. |
| i7-1165G7, 4 cores | ~8–12 tok/s on a 3–4B Q4 model, ~3 tok/s on 8B | **Do not put an LLM in the hot path.** An 8B model means 10+ second replies. |
| 32 GB RAM | Abundant | Everything can stay resident in memory. No cold starts, ever. |

The naive design (mic → Whisper → LLM → TTS) would give you **6–12 second** responses on this machine. That doesn't feel like Siri; it feels broken.

**The fix: a tiered brain.** Most of what you'll actually say to Gideon is not a reasoning problem. "What time is it", "set a timer for 10 minutes", "volume up", "open Firefox", "pause the music" — those are pattern matches. Route them deterministically in <1 ms and never wake the LLM at all.

---

## 2. Architecture

```
                        ┌─────────────────────────────────────────┐
   mic (PipeWire)  ────▶│  gideon-daemon  (one Python process)     │
                        │  systemd --user, resident, ~1.5 GB RSS   │
                        └─────────────────────────────────────────┘
                                          │
   ┌──────────────────────────────────────┴──────────────────────────────┐
   │                                                                     │
   │  [0] CAPTURE     sounddevice, 16 kHz mono, 80 ms ring buffer        │
   │        │                                                            │
   │  [1] WAKE WORD   openWakeWord "hey_gideon.onnx"    ~3% of one core  │
   │        │          ← the ONLY stage running 24/7                     │
   │        ▼  (score > 0.6)                                             │
   │  [2] ENDPOINT    silero-vad → record until 700 ms silence           │
   │        │          (this is what makes it feel responsive)           │
   │        ▼                                                            │
   │  [3] STT         faster-whisper small.en on MX450 (CUDA int8)       │
   │        │          ~400 ms for a 3 s utterance                       │
   │        ▼                                                            │
   │  [4] ROUTER  ──────────────────────────────────────────┐            │
   │        │                                               │            │
   │        ├─ Tier 0: rule/regex intents        <1 ms  ────┤            │
   │        ├─ Tier 1: Ollama qwen3:4b (local)   ~1.5 s ────┤            │
   │        └─ Tier 2: `claude -p` headless      ~5-15 s ───┤            │
   │                                                        │            │
   │        ▼                                               ▼            │
   │  [5] ACTUATE     dbus / pactl / playerctl / shell   (side effects)  │
   │        │                                                            │
   │  [6] TTS         Piper en_US-lessac-medium, CPU     ~300 ms         │
   │        │          streamed sentence-by-sentence                     │
   │        ▼                                                            │
   │  [7] BARGE-IN    mute wake detector while speaking; ESC/word to stop│
   └─────────────────────────────────────────────────────────────────────┘
```

### Latency budget (what you'll actually feel)

| Path | Wake→VAD | STT | Think | TTS | **Total** |
|---|---|---|---|---|---|
| Tier 0 "set a timer for 5 minutes" | 250 ms | 400 ms | ~0 | 300 ms | **~1.0 s** |
| Tier 1 "what's a good name for a cat" | 250 ms | 400 ms | 1.5 s | 300 ms | **~2.5 s** |
| Tier 2 "refactor the auth module" | 250 ms | 400 ms | 5–15 s | 300 ms | **~6–16 s** |

Tier 2 gets an immediate spoken ack ("On it.") so the silence never feels like a hang.

---

## 3. Component choices — all free, no keys

| Stage | Pick | Why | License |
|---|---|---|---|
| Capture | **sounddevice** (PortAudio→PipeWire) | Works on Wayland; no PulseAudio shim needed | MIT |
| Wake word | **openWakeWord** | Fully open, custom wake words trainable from **synthetic TTS audio only** — no recording sessions. Runs on CPU at ~3%. | Apache-2.0 |
| VAD | **silero-vad** (ONNX) | ~1 ms/chunk, far better than webrtcvad at rejecting keyboard clicks and fan noise | MIT |
| STT | **faster-whisper** `small.en`, `int8_float16` on CUDA | Fits the 2 GB MX450; 4–6× realtime | MIT |
| Local LLM | **Ollama** + `qwen3:4b-instruct` (Q4_K_M, ~2.5 GB, CPU) | Best instruction-following per byte at this size; runs on CPU at usable speed | Apache-2.0 |
| Escalation | **Claude Code headless** (`claude -p --output-format json`) | Uses your **existing subscription** — no separate API key, no per-token cost. Gives real reasoning + tool use + filesystem access on hard queries. | — |
| TTS | **Piper** `en_US-lessac-medium` | Fastest CPU TTS that still sounds human; ~20× realtime here | MIT |
| Service | `systemd --user` unit | Auto-start on login, auto-restart, `journalctl` logs | — |

**Why no Porcupine:** its free tier is personal-use-only and requires an access key with periodic online activation. openWakeWord has neither string attached.

---

## 4. The router — the heart of the design

```python
def route(text: str) -> Response:
    # Tier 0 — deterministic. ~30 intents covers 80% of daily use.
    if intent := match_rules(text):
        return intent.run()                      # <1 ms, no model touched

    # Tier 2 — explicit escalation, user-triggered by phrasing
    if is_agentic(text):        # "in my project", "write", "fix", "look up"
        speak("On it.")
        return claude_code(text)                 # subprocess, streamed

    # Tier 1 — default conversational fallback
    return ollama_chat(text)                     # 4B local, 2-sentence cap
```

**Tier 0 intent set (build these first):**
`time` · `date` · `timer/alarm` · `volume up|down|mute|set N` · `brightness` · `play|pause|next|previous` (playerctl) · `open <app>` · `lock screen` · `battery` · `wifi status` · `weather` (wttr.in, no key) · `what's on my calendar` (khal/local) · `note this down` · `screenshot` · `sleep` · `nevermind` (cancel)

Each intent is a small dataclass with a regex, a slot parser, and a handler. Adding one is ~10 lines. **This is where the assistant actually lives** — the LLM tiers are the exception path, not the norm.

### Actuation on Ubuntu 26.04 / Wayland
| Want | Use |
|---|---|
| Volume | `wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+` |
| Media | `playerctl play-pause` |
| Notifications | `notify-send` |
| Launch app | `gtk-launch <desktop-id>` |
| Brightness | `brightnessctl` |
| Window control | `gdbus` → GNOME Shell eval is locked down on GNOME 50; prefer a small **GNOME extension** exposing a D-Bus method, or `ydotool` (needs uinput group) |

Wayland deliberately blocks synthetic input. Plan for **D-Bus first, ydotool as last resort.**

---

## 5. Repo layout

```
Gideon/
├── docs/PLAN.md               ← this file
├── pyproject.toml             ← uv-managed, pinned to Python 3.12
├── gideon/
│   ├── __main__.py            ← asyncio event loop, stage wiring
│   ├── audio.py               ← capture, ring buffer, output ducking
│   ├── wake.py                ← openWakeWord
│   ├── vad.py                 ← silero endpointing
│   ├── stt.py                 ← faster-whisper
│   ├── tts.py                 ← Piper, sentence-streamed
│   ├── router.py              ← the tier logic above
│   ├── brains/
│   │   ├── rules.py           ← Tier 0 intents
│   │   ├── local_llm.py       ← Ollama client
│   │   └── claude_code.py     ← subprocess wrapper
│   ├── actions/               ← one module per capability
│   └── config.toml            ← thresholds, model paths, voice
├── models/                    ← .onnx + .gguf, gitignored
├── scripts/train_wakeword.py  ← synthetic "hey gideon" data → model
└── systemd/gideon.service
```

**Python note (corrected in v0.1):** the whole stack *does* install cleanly on Python 3.14. The shipped `.deb` nevertheless vendors its own CPython 3.12 — not because 3.14 fails, but because the package must install identically on Ubuntu 24.04 (3.12) through 26.04 (3.14) without depending on the system interpreter.

---

## 6. Build order

| Phase | Goal | Proof it works |
|---|---|---|
| **1. Loop** | Hardcoded wake key (spacebar) → record → Whisper → print | You see your words in the terminal |
| **2. Voice out** | Add Piper; echo the transcript back | Gideon repeats you |
| **3. Wake word** | Train `hey_gideon.onnx` from synthetic TTS; replace spacebar | Say it from across the room |
| **4. Tier 0** | 10 rule intents + actuation | Timers, volume, apps all work with zero models |
| **5. Tier 1** | Ollama fallback, 2-sentence system prompt | Open questions get answers |
| **6. Tier 2** | `claude -p` escalation with spoken ack | "Gideon, what's failing in my tests?" |
| **7. Harden** | systemd unit, echo cancel, barge-in, false-accept tuning | Runs for a week without you touching it |

Phases 1–4 give you a genuinely useful assistant. 5–6 are upside.

---

## 7. Known traps

1. **Feedback loop.** Gideon hears his own TTS and re-triggers. Fix cheaply by gating the wake detector during playback; fix properly with PipeWire `module-echo-cancel`. Do the cheap one in Phase 2.
2. **False accepts.** "Hey Gideon" is uncommon, which is good, but tune the threshold against a few hours of your actual ambient audio, not a quiet room. Log every near-miss score from day one.
3. **Fan noise / thermals.** Always-on wake detection at 3% CPU is fine. The *LLM* is what spins the fan — another reason Tier 0 matters.
4. **Whisper hallucination on silence.** Whisper invents text ("Thank you.") from near-silent audio. VAD gating plus a `no_speech_prob` threshold kills this.
5. **2 GB VRAM ceiling.** If STT and anything else contend for the MX450, you'll hit OOM. Keep the GPU exclusively for Whisper; check `nvidia-smi` before assuming it's free.
6. **Claude Code headless is not instant.** Never route Tier 2 without a spoken acknowledgement first.

---

## 8. Cost

**$0.** Every component is permissively licensed and runs locally. Tier 2 rides your existing Claude Code subscription. No API keys anywhere in the config.


---

## 9. Corrections from building v0.1

Three assumptions in the sections above were wrong once measured on the actual
hardware. They are left in place for context; these are the corrections.

### The GPU is not needed at all
Sections 1–2 budget STT onto the MX450. Measured, CPU-only, on the i7-1165G7:

| | measured |
|---|---|
| `tiny.en` int8, 4 threads | **0.22–0.26 s** per utterance (6× realtime) |
| `base.en` int8 | 0.33–0.36 s |
| `small.en` int8 | ~0.93 s |
| piper `en_US-lessac-medium` | **0.08 s** (~20× realtime) |

CPU is comfortably fast enough, so v0.1 ships **no CUDA dependency at all**. This
makes the package far smaller, removes the 2 GB VRAM ceiling as a design
constraint, and means it runs on machines with no discrete GPU. The MX450 is
unused.

### "Gideon" is heard as "get in" — and a bigger model does not help
The most important finding, and one that only appears when you test the real
name. Whisper renders "Gideon" as **"get in"** at *every* model size:

```
tiny.en    'Hey Gideon.'  ->  'Hey, get in.'
base.en    'Hey Gideon.'  ->  'Hey, get in!'
small.en   'Hey Gideon.'  ->  'Hey, get in!'
```

Scaling the model buys nothing here and costs 4× the latency. The fix belongs in
the matcher: `wake_phrases` carries phonetic variants, each requiring a `hey`/`hi`
prefix so ordinary speech ("let me get in the car") does not trigger. Measured
**5/6 recall, 0/6 false accepts** — on synthesised speech, not a real microphone.

The clean long-term fix remains a trained wake-word model (§3), which listens to
acoustics instead of routing the name through a transcriber biased toward common
English words.

### v0.1 uses STT-based wake detection, not openWakeWord
openWakeWord has no pretrained "gideon" model, and **0.6.0 stopped bundling models
in the wheel entirely** (0.4.0 shipped them). v0.1 therefore gates on Silero VAD
and runs Whisper per speech segment. Silero v4 is pinned by URL and sha256 in the
build script rather than extracted from openWakeWord, precisely because that
source vanished across a minor version bump.

### Packaging notes worth keeping
- `faster-whisper` imports `av` unconditionally at package import, even when you
  only ever pass it numpy arrays. It cannot be pruned (~103 MB).
- `openwakeword` is what drags in scipy + sklearn (~126 MB); not installing it
  is what keeps the package under 600 MB.
- `python3 -E` discards `PYTHONPATH`. The launcher injects `sys.path` explicitly
  so the vendored runtime stays isolated *and* actually finds its own code.
- uv's Python directory contains symlinks pointing outside itself — `cp -aL`,
  not `cp -a`, or the package ships a dangling link.
