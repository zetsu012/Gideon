# `src/gideon/ui/theme.py`

**One place for the colours, the words and the icons.**

Kept apart from the widgets so that "what does *listening* look like" is a data question with
one answer, shared by the tray icon, the HUD orb and the health panel. Changing the palette
changes all three at once and cannot leave them disagreeing about which state is which colour
— the one bug this UI must never have, since its entire purpose is to be believed.

| Name | Notes |
|---|---|
| `STATES` | state → (rgb, short label, tooltip sentence) |
| `SUBSYSTEMS` | health key → (friendly name, what it is) — drives the panel's row titles |
| `accent()` / `label()` / `describe()` / `hex_of()` | accessors; unknown states fall back to `offline` |
| `render_icons()` | draws one 22 px PNG per state into `$XDG_RUNTIME_DIR/gideon-ui/icons`, returns the directory |
| `icon_name(state)` | `gideon-<state>`, the themed name AppIndicator loads from that directory |

## Why the icons are drawn, not shipped

The set is one small glyph per state, they must all agree with the palette above, and a
themed icon *directory* is the only thing AppIndicator will reliably load on GNOME. Drawing
them at startup keeps the palette and the icons from drifting apart, and `$XDG_RUNTIME_DIR`
means they vanish on reboot.

**Offline is drawn hollow and struck through, not merely a different colour.** The indicator
has to survive a monochrome or symbolic panel theme, where every state would otherwise look
identical and the icon would silently stop meaning anything.
