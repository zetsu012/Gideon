# `src/gideon/ui/__init__.py`

**Package docstring only — and a rule.**

Everything in `ui/` runs on the **system python**, never the vendored runtime, for the same
reason `gideon/hotkey/` does: it needs PyGObject and GTK, which are apt packages and are
deliberately not part of the shipped closure (they would drag half the desktop stack into a
self-contained `.deb`).

Consequences, all of them load-bearing:

* No module here imports anything from `gideon.*`. The constants shared with the daemon —
  the socket path, the state names — are **re-stated** in `feed.py`, not imported, and must
  be kept in step with `core/state.py` and `ipc/control.py` by hand.
* The modules import each other with a `sys.path.insert(…parent…)` preamble, because they
  are executed as scripts and have no parent package at runtime.
* `build-deb.sh` chmods them `0755` and ships them as readable scripts.

Entry point: `python3 src/gideon/ui/tray.py`, or `gideon --ui`.
