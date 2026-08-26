# `src/gideon/hotkey/listener.py`

**The push-to-talk daemon.** Turns one key on one keyboard into a trigger for the voice
agent. Runs as its own user unit, `gideon-hotkey.service`, written by `gideon --setup-key`.

```bash
python3 src/gideon/hotkey/listener.py --device "Keychron" --keys KEY_MUTE
```

## Grab and re-inject

The device is **grabbed exclusively**, so the OS never sees that keyboard's events and the
trigger key stops toggling system mute. Every key that is *not* the trigger is re-injected
through `/dev/uinput`, so the keyboard keeps typing normally.

If uinput is unavailable the listener says so and continues in **grab-only mode** — the
whole keyboard goes quiet. That is fine for a dedicated remote and not fine for the
keyboard you type on, which is why `gideon --setup-key` checks the udev rule up front.

The grab is per-device: other input devices are untouched either way.

## Configuration

Flags or the matching environment variables, so the systemd unit can be edited without
touching the file:

| Variable | Flag | Meaning |
|---|---|---|
| `GIDEON_HOTKEY_DEVICE` | `--device` | substring of the device name |
| `GIDEON_HOTKEY_KEYS` | `--keys` | comma-separated `KEY_*` names |
| `GIDEON_TRIGGER_CMD` | `--command` | command run on key-down when no daemon answers |

`--learn` records the next pressed key to `~/.config/gideon/hotkey-key` instead of acting
on it; that is how `gideon --setup-key` captures the choice.

## What a press does

First it tries the control socket — `send("wake")` to `socket_path()` — which arms the
**running** daemon. Only if nothing is listening does it fall back to spawning
`GIDEON_TRIGGER_CMD`. That ordering is the whole point: a key press must not start a second
Gideon.

`socket_path()` duplicates `gideon.ipc.control.default_path()` deliberately — this file runs
on the system python and cannot import the vendored package. **Change one, change both.**

Note that the module-level `DEFAULT_COMMAND` (`REPO / 'run-local.sh'`) is a stale fallback
constant: in practice the trigger command is always supplied by `gideon --setup-key` through
`GIDEON_TRIGGER_CMD`, which resolves `scripts/run-local.sh` correctly.

| | |
|---|---|
| Imports | `evdev`, `device.py`, stdlib |
| Runs on | system python, as `gideon-hotkey.service` |
| Requires | `input` group membership; `/etc/udev/rules.d/99-uinput.rules` for re-injection |
| See also | `docs/HOTKEY.md`, `docs/reference/src/gideon/ipc/control.md` |
