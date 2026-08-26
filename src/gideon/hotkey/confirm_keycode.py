#!/usr/bin/env python3
"""Step 2: print raw events from one device so you can confirm the keycode.

    python3 hotkey/confirm_keycode.py "Keychron"

The device is opened WITHOUT grabbing it, so the key still does whatever it
normally does while you probe.  Press the volume/mute button and note the
KEY_* name that appears next to "down" - that string is what you pass to
listener.py as GIDEON_HOTKEY_KEYS.

Some keyboards emit the media key on a different event node than the letter
keys.  If nothing prints, run discover_devices.py again and try the other node
belonging to the same keyboard.
"""
from __future__ import annotations
import argparse, sys

try:
    from evdev import InputDevice, ecodes
except ImportError:
    sys.exit("python3-evdev is not installed:  sudo apt install python3-evdev")

from device import key_name, permission_hint, resolve_by_name   # noqa: E402

_VALUE = {0: "up", 1: "down", 2: "hold"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="substring of the device name (case-insensitive)")
    args = ap.parse_args()

    path = resolve_by_name(args.name)
    if path is None:
        sys.exit(permission_hint() or
                 f"no input device matching {args.name!r} - run discover_devices.py")
    dev = InputDevice(path)
    print(f"reading {dev.name!r} ({dev.path}) - press the button, Ctrl-C to stop\n")
    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_KEY:
                key = key_name(event.code)
                print(f"EV_KEY  code={event.code:<4} {key:<20} {_VALUE.get(event.value, event.value)}")
    except KeyboardInterrupt:
        print()
    except OSError as exc:
        sys.exit(f"device went away: {exc}")
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
