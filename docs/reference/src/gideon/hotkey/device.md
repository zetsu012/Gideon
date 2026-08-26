# `src/gideon/hotkey/device.py`

**Shared helpers for the four hotkey scripts.** Imported by them as a plain top-level
module (`from device import …`) after each inserts its own directory on `sys.path` — they
are scripts, not a package.

## `resolve_by_name(needle, require_key=None)`

Resolves an input device **by name, never by path**. A Bluetooth keyboard lands on a
different `/dev/input/eventX` after every reconnect, so the path is not a stable
identifier; the reported name is. `require_key` filters to nodes that actually report the
key in question — multimedia keys often live on a different event node of the same
keyboard than the letters.

## `permission_hint()`

Turns the most common failure into a sentence the user can act on. A zero-device scan looks
identical to "keyboard not connected", but the kernel node count (from
`/proc/bus/input/devices`) and the count evdev can open diverge **exactly** when the
session lacks the `input` group — including the case where `usermod` has already run but
the login session predates it. The hint names `usermod -aG input` and offers
`sg input -c '…'` for testing without logging out.

## `key_name(code)`

`KEY_*` name for a keycode, for human-readable logging.

| | |
|---|---|
| Imports | `evdev`, stdlib `grp`/`os` |
| Imported by | `listener.py`, `confirm_keycode.py`, `list_keyboards.py` |
| Runs on | system python |
