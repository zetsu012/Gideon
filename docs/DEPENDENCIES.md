# Dependencies

Everything Gideon needs, in one place: what the `.deb` installs for you, what is baked
inside it, what you install by hand, and what is deliberately left out.

The machine-readable manifests live in [`requirements/`](../requirements/) —
`python-runtime.txt` is **read by the build**, the rest mirror `packaging/debian/control`
and the `need` checks in `scripts/build-deb.sh`. See
[`docs/reference/requirements/README.md`](reference/requirements/README.md).

**Summary.** One apt command installs everything required. The vendored Python, all 28
Python packages and all three models are inside the package — first run needs no network.
The only things a user ever installs manually are `libportaudio2` when running from source,
and Ollama if they want real answers instead of canned ones.

---

## 1. What you install manually

| # | Component | Command | Required? |
|---|---|---|---|
| 1 | **The package itself** | `sudo apt install ./gideon_0.1.0_amd64.deb` | yes — pulls every apt dependency in §2 automatically |
| 2 | **libportaudio2** | `sudo apt install libportaudio2` | **only when running from source** with `scripts/run-local.sh`. The `.deb` depends on it, so an installed Gideon never needs this step |
| 3 | **Ollama** | `curl -fsSL https://ollama.com/install.sh \| sh` | optional — without it Gideon falls back to canned replies, quietly and without error |
| 4 | **A non-reasoning model** | `ollama pull llama3.2:1b` | optional, with Ollama. Must be non-reasoning: see §6 |
| 5 | **`input` group** | `sudo usermod -aG input $USER` (then re-login) | only for push-to-talk. `gideon --setup-key` checks this and prints the command |
| 6 | **uinput udev rule** | written by `gideon --setup-key` | only for push-to-talk, and only so non-trigger keys keep typing |

Nothing else. No pip install, no model download, no API key, no network at first run.

## 2. Build-host tools

Needed only to *build* the `.deb`, never to run it — `uv`, `curl`, `sha256sum`,
`dpkg-deb`, `fakeroot`, `strip`. `scripts/build-deb.sh` checks each and names the missing
one. See `requirements/build-tools.txt`.

---
## 3. System packages (apt) — installed automatically by the `.deb`

| Package | Why |
|---|---|
| `libc6 (≥2.35)` | C runtime. The floor is what makes 24.04 the minimum Ubuntu. |
| `libstdc++6` | C++ runtime for onnxruntime and ctranslate2. |
| `libgomp1` | OpenMP — the multi-threading that makes CPU inference fast. |
| `libportaudio2` | **The microphone and speakers.** `sounddevice` dlopen's it at runtime. The one library not vendored, because audio must use the system's own stack. |
| `libsndfile1` | Audio file decoding used by the audio stack. |
| *Recommends:* `pipewire`, `pipewire-pulse`, `wireplumber` | Ubuntu's audio server. Already present on any normal desktop. |

## 4. Python packages — bundled inside the `.deb`, nothing to install

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
v0.1 does not use it — see `docs/ARCHITECTURE.md` §6.

**Not a Python dependency at all:** Ollama. Gideon talks to it over HTTP with
`urllib` from the standard library, which is why the LLM is fully optional.

## 5. Models — bundled, no download at first run

| Model | Size | Role |
|---|---|---|
| `faster-whisper tiny.en` | 75 MB | Speech recognition, English-only. |
| `piper en_US-lessac-medium` | 61 MB | The voice you hear. |
| `silero_vad.onnx` (v4) | 1.8 MB | Decides which frames contain speech. |

## 6. Optional — the Tier 1 brain (Ollama)

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

---

## 7. Deliberately not installed

| Package | Why not |
|---|---|
| `openwakeword` | v0.1 detects the wake phrase in the Whisper transcript instead; there is no pretrained "gideon" model to use |
| `scipy`, `scikit-learn` | reachable only through openwakeword — ~126 MB removed by the build |
| `hf_xet` | HuggingFace Xet transfer backend; models are baked in and `HF_HUB_OFFLINE=1` is set |
| the `ollama` SDK | the LLM client speaks HTTP with stdlib `urllib`, so an optional feature adds no dependency |

`av` is the exception that stays: it is unused at runtime, but
`faster_whisper/audio.py` imports it unconditionally at package-import time.
See `requirements/python-optional.txt`.

## 8. Keeping this in sync

| If you change | Also update |
|---|---|
| a Python dependency | `requirements/python-runtime.txt` (the build reads it), then regenerate `requirements/python-locked.txt` |
| an apt dependency | `packaging/debian/control` **and** `requirements/system-apt.txt` |
| a build tool | the `need` line in `scripts/build-deb.sh` **and** `requirements/build-tools.txt` |
| a model | `scripts/build-deb.sh` (and the SHA pin, for Silero) and §5c above |
