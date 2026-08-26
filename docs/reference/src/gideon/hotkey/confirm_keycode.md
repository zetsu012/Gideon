# `src/gideon/hotkey/confirm_keycode.py`

**Step 2 of manual key setup.** Prints raw key events from one device so you can read off
the `KEY_*` name of the button you want.

```bash
python3 src/gideon/hotkey/confirm_keycode.py "Keychron"
```

The device is opened **without grabbing it**, so the key keeps doing whatever it normally
does while you probe — a volume key still changes the volume. Press the button and note
the `KEY_*` shown next to `down`; that string is what goes in `GIDEON_HOTKEY_KEYS`.

If nothing prints, the key is on another event node of the same keyboard — re-run
`discover_devices.py` and try the sibling node.

Values are mapped `0 → up`, `1 → down`, `2 → hold`.
