"""Resolve an input device by NAME, never by path.

A Bluetooth keyboard lands on a different /dev/input/eventX after every
reconnect, so the path is not a stable identifier; the reported name is.
"""
from __future__ import annotations

import grp, os

from evdev import InputDevice, list_devices, ecodes


def permission_hint() -> str | None:
    """Explain a zero-device scan, which otherwise looks like 'not connected'.

    The kernel node count and the count evdev can actually open diverge exactly
    when the session lacks the 'input' group - including the common case where
    usermod has run but the login session predates it.
    """
    try:
        kernel = sum(1 for line in open("/proc/bus/input/devices") if line.startswith("N: Name"))
    except OSError:
        return None
    if kernel == 0 or list_devices():
        return None
    try:
        in_group = "input" in {grp.getgrgid(g).gr_name for g in os.getgroups()}
    except KeyError:
        in_group = False
    if in_group:
        return (f"the kernel lists {kernel} input devices but none are readable - "
                "check the permissions on /dev/input/event*")
    return (f"the kernel lists {kernel} input devices but none are readable: this session "
            "is not in the 'input' group.\n"
            "  sudo usermod -aG input $USER   then log out and back in\n"
            "  (to test without logging out:  sg input -c '<command>')")


def resolve_by_name(needle: str, *, require_key: int | None = None) -> str | None:
    """Return the path of the first device whose name contains `needle`.

    `require_key` restricts the match to nodes that actually advertise that key
    code, which is how the media-key node of a keyboard is told apart from the
    node carrying the letter keys when both share a name.
    """
    needle = needle.lower()
    fallback = None
    for path in sorted(list_devices()):
        try:
            dev = InputDevice(path)
        except OSError:                     # unreadable or raced with a disconnect
            continue
        try:
            if needle not in dev.name.lower():
                continue
            if require_key is None:
                return path
            if require_key in dev.capabilities().get(ecodes.EV_KEY, ()):
                return path
            fallback = fallback or path
        finally:
            dev.close()          # InputDevice is not a context manager in evdev 1.9
    return fallback


def key_name(code: int) -> str:
    """Human name for a key code.

    ecodes.KEY[code] is a list/tuple whenever several names share one code, and
    the aliases that bound the table (KEY_MIN_INTERESTING == KEY_MUTE == 113,
    KEY_MAX) sort first while being useless to a reader. Prefer a real name.
    """
    names = ecodes.KEY.get(code, f"KEY_{code}")
    if isinstance(names, (list, tuple)):
        real = [n for n in names if not n.startswith(("KEY_MIN", "KEY_MAX"))]
        return (real or list(names))[0]
    return names
