# `src/gideon/audio/__init__.py`

Docstring only — no logic, no re-exports.

**Owns:** device input — the only place an input device is opened

**Contains:** `capture.py`

Importers reach the modules directly (`from .audio.capture import …`) rather than through this
file, so the package boundary stays a directory boundary and importing one stage never
drags in another's dependencies. Keep it empty: `sounddevice` is imported lazily inside `Microphone.__enter__` so `--selftest` runs on a machine with no PortAudio; an import here would undo that.
