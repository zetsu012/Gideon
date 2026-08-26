# `src/gideon/hotkey/discover_devices.py`

**Step 1 of manual key setup.** Lists every input device with path, name, physical address
and capability classes.

```bash
python3 src/gideon/hotkey/discover_devices.py
```

Prints **every node**, without de-duplicating by name, because multimedia keys frequently
live on a second event node of the same keyboard. Find your keyboard, take a distinctive
substring of its name, and pass it to `confirm_keycode.py`.

Exits with the `input`-group instructions if nothing under `/dev/input` is readable, and
with an apt hint if `python3-evdev` is missing. Unreadable individual nodes are printed as
`<unreadable: …>` rather than aborting the scan.

`gideon --setup-key` automates this step; the script is the manual fallback when the menu
does not show the device you expected.
