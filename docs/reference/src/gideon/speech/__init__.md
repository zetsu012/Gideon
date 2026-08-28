# `src/gideon/speech/__init__.py`

Docstring only — no logic, no re-exports.

**Owns:** the three models, one file each

**Contains:** `vad.py`, `stt.py`, `tts.py`

Importers reach the modules directly (`from .speech.vad import …`) rather than through this
file, so the package boundary stays a directory boundary and importing one stage never
drags in another's dependencies. Keep it empty: each model costs seconds to load, and `--say` must load only Piper.
