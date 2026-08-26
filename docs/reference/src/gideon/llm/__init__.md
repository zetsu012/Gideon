# `src/gideon/llm/__init__.py`

Docstring only — no logic, no re-exports.

**Owns:** the optional Tier 1 brain

**Contains:** `client.py`

Importers reach the modules directly (`from .llm.client import …`) rather than through this
file, so the package boundary stays a directory boundary and importing one stage never
drags in another's dependencies. Keep it empty: the LLM is optional; nothing about its absence may cost anything.
