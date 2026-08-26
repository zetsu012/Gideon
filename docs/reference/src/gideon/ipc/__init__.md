# `src/gideon/ipc/__init__.py`

Docstring only — no logic, no re-exports.

**Owns:** out-of-band signals — one socket, one bit

**Contains:** `control.py`

Importers reach the modules directly (`from .ipc.control import …`) rather than through this
file, so the package boundary stays a directory boundary and importing one stage never
drags in another's dependencies. Keep it empty: the socket is also constructed by `--selftest` and by `cli/setup.py`.
