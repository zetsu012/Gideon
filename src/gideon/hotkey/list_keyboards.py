#!/usr/bin/env python3
"""Print the name of every device that looks like a keyboard, one per line.

Used by setup.sh to build its menu. A keyboard is a node that reports the
letter keys; the mouse/consumer nodes a combo device also registers are left
out, and duplicate names are collapsed.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evdev import InputDevice, list_devices, ecodes      # noqa: E402
from device import permission_hint                       # noqa: E402


def main() -> int:
    hint = permission_hint()
    if hint:
        print(hint, file=sys.stderr)
        return 1
    seen = []
    for path in sorted(list_devices()):
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        try:
            keys = dev.capabilities().get(ecodes.EV_KEY, ())
            # Skip our own uinput clone: selecting it would grab a virtual
            # device and forward to a second one, and the real key would still mute.
            if dev.name.startswith("gideon-hotkey"):
                continue
            if ecodes.KEY_A in keys and ecodes.KEY_Z in keys and dev.name not in seen:
                seen.append(dev.name)
        finally:
            dev.close()
    print("\n".join(seen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
