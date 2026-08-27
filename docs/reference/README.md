# File reference

One document per file, at the same relative path as the file itself. Each covers what the
file is for, its public surface, and the invariants that are not obvious from reading it.

## Application — `src/gideon/`

| File | Document | Role |
|---|---|---|
| `__init__.py` | [__init__.md](src/gideon/__init__.md) | version only |
| `__main__.py` | [__main__.md](src/gideon/__main__.md) | daemon: CLI, endpointing, the pipeline loop |
| `core/__init__.py` | [core/__init__.md](src/gideon/core/__init__.md) | package docstring; why it stays empty |
| `core/config.py` | [core/config.md](src/gideon/core/config.md) | every tunable, TOML resolution, model paths |
| `core/state.py` | [core/state.md](src/gideon/core/state.md) | pipeline state + per-subsystem health; what the UI renders |
| `core/credentials.py` | [core/credentials.md](src/gideon/core/credentials.md) | API keys, 0600, out of the world-readable config |
| `audio/__init__.py` | [audio/__init__.md](src/gideon/audio/__init__.md) | package docstring; why it stays empty |
| `audio/capture.py` | [audio/capture.md](src/gideon/audio/capture.md) | microphone → bounded frame queue |
| `speech/__init__.py` | [speech/__init__.md](src/gideon/speech/__init__.md) | package docstring; why it stays empty |
| `speech/vad.py` | [speech/vad.md](src/gideon/speech/vad.md) | Silero v4 voice-activity detection |
| `speech/stt.py` | [speech/stt.md](src/gideon/speech/stt.md) | faster-whisper speech to text |
| `speech/tts.py` | [speech/tts.md](src/gideon/speech/tts.md) | Piper text to speech and playback |
| `speech/speaker.py` | [speech/speaker.md](src/gideon/speech/speaker.md) | ECAPA-TDNN: is this the enrolled voice? |
| `nlu/__init__.py` | [nlu/__init__.md](src/gideon/nlu/__init__.md) | package docstring; why it stays empty |
| `nlu/wake.py` | [nlu/wake.md](src/gideon/nlu/wake.md) | wake-phrase matching over the transcript |
| `nlu/brain.py` | [nlu/brain.md](src/gideon/nlu/brain.md) | Tier 0/1/2 reply router |
| `llm/__init__.py` | [llm/__init__.md](src/gideon/llm/__init__.md) | package docstring; why it stays empty |
| `llm/client.py` | [llm/client.md](src/gideon/llm/client.md) | Ollama HTTP client, optional |
| `llm/provider.py` | [llm/provider.md](src/gideon/llm/provider.md) | the cloud provider table; `ollama` is not in it |
| `llm/cloud.py` | [llm/cloud.md](src/gideon/llm/cloud.md) | OpenAI-compatible cloud client (Cerebras, OpenRouter) |
| `llm/fallback.py` | [llm/fallback.md](src/gideon/llm/fallback.md) | cloud first, local second, canned last |
| `ipc/__init__.py` | [ipc/__init__.md](src/gideon/ipc/__init__.md) | package docstring; why it stays empty |
| `ipc/control.py` | [ipc/control.md](src/gideon/ipc/control.md) | unix socket: arms push-to-talk, publishes status |
| `cli/__init__.py` | [cli/__init__.md](src/gideon/cli/__init__.md) | package docstring; why it stays empty |
| `cli/setup.py` | [cli/setup.md](src/gideon/cli/setup.md) | `gideon --setup` / `--setup-key` |
| `cli/enroll.py` | [cli/enroll.md](src/gideon/cli/enroll.md) | `gideon --enroll`: record the owner's voiceprint |
| `cli/provider.py` | [cli/provider.md](src/gideon/cli/provider.md) | `gideon --provider`: pick the Tier 1 brain |
| `cli/ui.py` | [cli/ui.md](src/gideon/cli/ui.md) | `gideon --ui`: execs the indicator on the system python |

## Keyboard trigger — `src/gideon/hotkey/` (system python)

| File | Document | Role |
|---|---|---|
| `__init__.py` | [hotkey/__init__.md](src/gideon/hotkey/__init__.md) | why these are executed, never imported |
| `device.py` | [hotkey/device.md](src/gideon/hotkey/device.md) | resolve by name; permission diagnostics |
| `listener.py` | [hotkey/listener.md](src/gideon/hotkey/listener.md) | grab the key, re-inject the rest, signal the daemon |
| `discover_devices.py` | [hotkey/discover_devices.md](src/gideon/hotkey/discover_devices.md) | manual step 1: list devices |
| `confirm_keycode.py` | [hotkey/confirm_keycode.md](src/gideon/hotkey/confirm_keycode.md) | manual step 2: identify the key |
| `list_keyboards.py` | [hotkey/list_keyboards.md](src/gideon/hotkey/list_keyboards.md) | menu source for `--setup-key` |

## Tray indicator — `src/gideon/ui/` (system python)

| File | Document | Role |
|---|---|---|
| `__init__.py` | [ui/__init__.md](src/gideon/ui/__init__.md) | why these are executed, never imported |
| `feed.py` | [ui/feed.md](src/gideon/ui/feed.md) | subscribes to the daemon; reconnects; decides "offline" |
| `theme.py` | [ui/theme.md](src/gideon/ui/theme.md) | one palette, one wording, the drawn icons |
| `bubble.py` | [ui/bubble.md](src/gideon/ui/bubble.md) | one chat bubble; the entry and streaming animations |
| `hud.py` | [ui/hud.md](src/gideon/ui/hud.md) | on-screen overlay: the chat thread and the state |
| `panel.py` | [ui/panel.md](src/gideon/ui/panel.md) | health panel: one row per subsystem, all measured |
| `tray.py` | [ui/tray.md](src/gideon/ui/tray.md) | the indicator itself; `gideon --ui` |

## Scripts — `scripts/`

| File | Document | Role |
|---|---|---|
| `build-deb.sh` | [scripts/build-deb.md](scripts/build-deb.md) | builds the self-contained `.deb` |
| `run-local.sh` | [scripts/run-local.md](scripts/run-local.md) | runs the working copy, no install |

## Packaging — `packaging/`

| File | Document | Role |
|---|---|---|
| `config/config.toml` | [packaging/config/config.toml.md](packaging/config/config.toml.md) | shipped defaults → `/etc/gideon/` |
| `launcher/gideon.launcher` | [packaging/launcher/gideon.launcher.md](packaging/launcher/gideon.launcher.md) | → `/usr/bin/gideon` |
| `systemd/gideon.service` | [packaging/systemd/gideon.service.md](packaging/systemd/gideon.service.md) | systemd **user** unit |
| `systemd/gideon-ui.service` | [packaging/systemd/gideon-ui.service.md](packaging/systemd/gideon-ui.service.md) | systemd **user** unit for the indicator |
| `debian/control` | [packaging/debian/control.md](packaging/debian/control.md) | package metadata and `Depends:` |
| `debian/conffiles` | [packaging/debian/conffiles.md](packaging/debian/conffiles.md) | protects `/etc/gideon/config.toml` on upgrade |
| `debian/postinst` | [packaging/debian/postinst.md](packaging/debian/postinst.md) | verify runtime, enable the unit, print next steps |
| `debian/prerm` | [packaging/debian/prerm.md](packaging/debian/prerm.md) | disable and stop before removal |

## Dependencies — `requirements/`

| File | Document |
|---|---|
| all five manifests | [requirements/README.md](requirements/README.md) |

Narrative version: [`../DEPENDENCIES.md`](../DEPENDENCIES.md).
