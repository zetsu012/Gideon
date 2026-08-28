# `src/gideon/nlu/__init__.py`

Docstring only — no logic, no re-exports.

**Owns:** interpretation: pure functions and rules, no I/O and no models

**Contains:** `wake.py`, `brain.py`

Importers reach the modules directly (`from .nlu.wake import …`) rather than through this
file, so the package boundary stays a directory boundary and importing one stage never
drags in another's dependencies. Keep it empty: these are the cheapest modules in the system and must stay that way.
