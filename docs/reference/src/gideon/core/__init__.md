# `src/gideon/core/__init__.py`

Docstring only — no logic, no re-exports.

**Owns:** configuration

**Contains:** `config.py`

Importers reach the modules directly (`from .core.config import …`) rather than through this
file, so the package boundary stays a directory boundary and importing one stage never
drags in another's dependencies. Keep it empty: the daemon imports it before anything else, so cost here is paid on every invocation including `--say` and `--setup`.
