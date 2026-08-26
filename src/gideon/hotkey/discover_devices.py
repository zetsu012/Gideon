#!/usr/bin/env python3
"""Step 1: list every input device so you can identify the Bluetooth keyboard.

    python3 hotkey/discover_devices.py

Prints path, name, physical address and the capability classes each device
reports.  Look for the entry whose name matches your keyboard, then pass a
distinctive substring of that name to confirm_keycode.py / listener.py.
"""
from __future__ import annotations
import sys

try:
    from evdev import InputDevice, list_devices, ecodes
except ImportError:
    sys.exit("python3-evdev is not installed:  sudo apt install python3-evdev")


def main() -> int:
    paths = sorted(list_devices())
    if not paths:
        sys.exit("no readable devices under /dev/input - are you in the 'input' group?\n"
                 "  sudo usermod -aG input $USER   (then log out and back in)")
    for path in paths:
        try:
            dev = InputDevice(path)
        except OSError as exc:            # permissions, or device vanished mid-scan
            print(f"{path:20} <unreadable: {exc}>")
            continue
        try:
            caps = ",".join(ecodes.EV[t] for t in dev.capabilities() if t in ecodes.EV)
            # Multimedia keys often live on a second event node of the same
            # keyboard, so print every node rather than de-duplicating by name.
            print(f"{dev.path:20} {dev.name!r}\n{'':20} phys={dev.phys} caps={caps}")
        finally:
            dev.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
