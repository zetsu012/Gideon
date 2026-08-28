"""`gideon --ui`: start the tray indicator.

The indicator is GTK, and GTK is an apt package that is deliberately not in the
vendored runtime, so this cannot be an import - it is an exec of the SYSTEM
python on `gideon/ui/tray.py`, exactly as `setup.py` execs the evdev scripts in
`gideon/hotkey/`. Having the command live here anyway means a user never has to
know where the package put its files.
"""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path

SYSTEM_PY = "/usr/bin/python3"
TRAY = Path(__file__).resolve().parent.parent / "ui" / "tray.py"

APT_PACKAGES = ("python3-gi", "python3-gi-cairo", "gir1.2-gtk-3.0",
                "gir1.2-ayatanaappindicator3-0.1")
MISSING_GI = """\
The indicator needs PyGObject and GTK 3 from apt (they are not vendored):

    sudo apt install %s
""" % " ".join(APT_PACKAGES)

# python3-gi-cairo is separately checked because its absence is not an import
# error: GTK loads, the window appears, and only the drawn parts fail at
# runtime with "couldn't find foreign struct converter for cairo.Context".
PROBE = ("import gi; gi.require_version('Gtk','3.0');"
         "from gi.repository import Gtk; import cairo, gi.repository.cairo")


def have_gtk() -> bool:
    return subprocess.call([SYSTEM_PY, "-c", PROBE],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def launch(argv: list[str] | None = None, *, replace: bool = True) -> int:
    """Run the tray. `replace=True` hands the process over to it."""
    if not TRAY.is_file():
        print(f"indicator not installed: {TRAY} is missing", file=sys.stderr)
        return 2
    if not have_gtk():
        print(MISSING_GI, file=sys.stderr)
        return 2
    args = [SYSTEM_PY, str(TRAY), *(argv or [])]
    if replace:
        # No reason to keep the vendored interpreter resident behind it.
        os.execv(SYSTEM_PY, args)
    return subprocess.call(args)
