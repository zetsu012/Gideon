"""The desktop face of Gideon: a tray indicator, a HUD and a health panel.

This package runs on the SYSTEM python, never the vendored runtime, for the same
reason `gideon/hotkey/` does: it needs PyGObject and GTK, which are apt packages
and are deliberately not part of the shipped closure (they would drag half the
desktop stack into a self-contained .deb). So nothing here imports anything from
`gideon.*`, and the few constants shared with the daemon - the socket path, the
state names - are re-stated in `feed.py` rather than imported.

The modules are executed, not imported:

    python3 src/gideon/ui/tray.py        # or: gideon --ui
"""
