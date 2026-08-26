# `src/gideon/cli/ui.py`

**`gideon --ui`: starts the tray indicator.**

The indicator is GTK, and GTK is an apt package that is deliberately **not** in the vendored
runtime, so this cannot be an import — it is an `execv` of `/usr/bin/python3` on
`gideon/ui/tray.py`, exactly as `cli/setup.py` execs the evdev scripts in `gideon/hotkey/`.
Putting the command here anyway means a user never has to know where the package put its files.

| Name | Notes |
|---|---|
| `APT_PACKAGES` | `python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1` |
| `have_gtk()` | probes the system python |
| `launch(argv, replace=True)` | `replace` hands the process over, leaving no vendored interpreter resident behind it |

**Why the probe imports cairo too.** A missing `python3-gi-cairo` is not an import error: GTK
loads, the window appears, and only the *drawn* parts fail at runtime with `couldn't find
foreign struct converter for cairo.Context`. Checking it up front turns a half-broken HUD
into a clear instruction.
