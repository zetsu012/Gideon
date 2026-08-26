# Push-to-talk key

A key on an external keyboard stands in for the wake phrase: press it, then
just talk. Set it up with `gideon --setup-key` (or as the last step of
`gideon --setup`); everything below is what that command automates.

## How it coexists with the wake phrase

A press does **not** start a second Gideon. It sends `wake` to the control
socket of the daemon that is already running (`gideon.ipc.control`, bound at
`$XDG_RUNTIME_DIR/gideon.sock`), and the daemon treats the next utterance as a
query - the same code path as the follow-up window, logged `KEY`. The wake
phrase keeps working the whole time. One process, one microphone, two ways in.

If no daemon is listening, a press falls back to `gideon --once`, which reloads
the models every time. That is the fallback, not the design.

The arm expires after `hotkey_window_s` (10 s): pressing the key and walking
away must not turn some unrelated sentence into a query later.

## What the setup does

| step | why |
| --- | --- |
| `apt install python3-evdev` | the listener runs on the **system** python; evdev is not in the vendored runtime |
| `usermod -aG input $USER` | read `/dev/input/event*` without root |
| udev rule for `/dev/uinput` | the listener grabs the keyboard exclusively and replays every non-trigger key; without uinput the keyboard would go silent |
| pick a keyboard | resolved by **name**, never by path - a Bluetooth device lands on a different `/dev/input/eventX` after each reconnect |
| learn a key | recorded to `~/.config/gideon/hotkey-key` |
| install `gideon-hotkey.service` | user unit, `Restart=always` |

Group membership is fixed at login, so a fresh `usermod` means one logout
before the service can start. Setup detects this, enables the unit without
starting it, and says so.

## Modules

`gideon/hotkey/` is executed, never imported by the daemon:

| file | role |
| --- | --- |
| `listener.py` | the service: resolve by name → grab → arm the daemon on key-down, forward everything else |
| `device.py` | name-based resolution, key naming, and the "you are not in the input group" diagnosis |
| `list_keyboards.py` | keyboard names for the setup menu |
| `discover_devices.py` | every input device, for debugging |
| `confirm_keycode.py` | raw event stream from one device, for debugging |

## Debugging

```bash
journalctl --user -u gideon-hotkey -f
systemctl --user restart gideon-hotkey
gideon --setup-key                                    # rebind, or switch keyboards
python3 /opt/gideon/app/gideon/hotkey/discover_devices.py
python3 /opt/gideon/app/gideon/hotkey/confirm_keycode.py "NAME"
```

| symptom | cause |
| --- | --- |
| `not in the 'input' group` | the session predates the `usermod` - log out and back in |
| the whole keyboard stops typing | `/dev/uinput` not writable; re-run `gideon --setup-key` |
| `no daemon on ...` in the log | `gideon.service` is not running, so presses are slow one-shots |
| press arms, nothing happens | nothing was said within `hotkey_window_s` |


## "Press the button …" never returns

The keyboard is already grabbed — almost always by a `gideon-hotkey` listener from an earlier
setup. A grabbed device delivers its events to the grabber alone, so the learning step cannot
see the press no matter how many times you hit the key.

```bash
systemctl --user stop gideon-hotkey     # gideon --setup-key does this for you
```

You can confirm it from the device list: a running listener creates a uinput mirror named
`gideon-hotkey (<your keyboard>)`, so if that node exists, the real device is grabbed.

Since this fix, `listener.py --learn` probes for the grab and says so instead of hanging.

## The key stopped arming the daemon

If the key silently does nothing, check the control socket before suspecting the keyboard:

```bash
gideon --ui --health          # or: systemctl --user restart gideon
```

The listener's fallback, when the daemon cannot be reached, is to run a one-shot Gideon. So
a stranded socket looks like "the key is dead" while the wake phrase keeps working perfectly
— the two paths are independent.
