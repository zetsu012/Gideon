# `src/gideon/cli/setup.py`

**The whole first-run experience, as `gideon --setup` and `gideon --setup-key`.**

There is deliberately **no shell script and no repository checkout** in the setup path: the
.deb carries this module, so `gideon --setup` is the entire story on a new machine.

| Command | Does |
|---|---|
| `gideon --setup` | check the install, verify audio, start/restart the user daemon, then offer the key |
| `gideon --setup-key` | the push-to-talk key only |

## What it does for the key

1. `list_keyboards.py` → a menu of real keyboards (letter-key nodes only).
2. `listener.py --learn` → records the pressed key into `~/.config/gideon/hotkey-key`.
3. Writes `~/.config/systemd/user/gideon-hotkey.service` from `UNIT_TEMPLATE` and enables it.
4. Checks `input` group membership and the `/etc/udev/rules.d/99-uinput.rules` uinput rule,
   printing the exact command to fix either.

`trigger_command()` picks what a press falls back to when no daemon is listening:
`gideon --once` if installed, otherwise `scripts/run-local.sh --once` for a source checkout.

## The system-python boundary

`python3-evdev` is an apt package and is **not** in the vendored runtime, so
`gideon.hotkey.*` can never be imported from here — it is only ever **executed** via
`SYSTEM_PY` (`/usr/bin/python3`) as a subprocess. Every call in this file respects that.

`HOTKEY_DIR` is `Path(__file__).resolve().parent.parent / "hotkey"` — it points one level up
out of `cli/` into the package root.

Unit `Environment=` values are quoted in the template because systemd splits unquoted
values on whitespace and device names contain spaces.

| | |
|---|---|
| Imports | `..core.config`, `..ipc.control`, stdlib `grp`/`shutil`/`subprocess` |
| Imported by | `__main__`, lazily, before the model check |
| See also | `docs/HOTKEY.md` |


## `learn_key()` stands the listener down

An already-running key listener holds an exclusive grab on the keyboard, so learning a new
key would block forever on a press it can never see. This is specifically the **second** run
— the one where someone changes their key, having succeeded the first time. So `learn_key()`
stops `gideon-hotkey.service` first and, if learning does not succeed, starts it again so the
machine is left as it was found. On the success path `install_unit()` starts it.

## `setup_indicator()`

Offered as part of the ordinary flow, because a daemon with no window is indistinguishable
from a dead one. Still optional: GTK is apt-installed and a headless box has no reason to
carry it. In a source checkout there is no unit to enable, so it prints `gideon --ui` instead.
