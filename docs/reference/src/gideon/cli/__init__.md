# `src/gideon/cli/__init__.py`

Docstring only — no logic, no re-exports.

**Owns:** user-facing interactive flows

**Contains:** `setup.py`

Importers reach the modules directly (`from .cli.setup import …`) rather than through this
file, so the package boundary stays a directory boundary and importing one stage never
drags in another's dependencies. Keep it empty: `__main__` imports `setup` lazily, and deliberately before the model-existence check.
