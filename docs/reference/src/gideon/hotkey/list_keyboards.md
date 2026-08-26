# `src/gideon/hotkey/list_keyboards.py`

**Machine-readable device list: one keyboard name per line, on stdout.** This is what
`gideon --setup-key` parses to build its menu.

"Keyboard" means a node reporting both `KEY_A` and `KEY_Z`, which excludes the mouse and
consumer-control nodes a combo device also registers. Duplicate names are collapsed.

Nodes named `gideon-hotkey*` are skipped: that is the script's own uinput clone, and
selecting it would grab a virtual device and forward to a second one while the real key
still muted.

On a permission problem it prints `permission_hint()` to **stderr** and exits `1`, keeping
stdout clean for the caller.
