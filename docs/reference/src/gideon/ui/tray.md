# `src/gideon/ui/tray.py`

**The tray indicator: the proof that the daemon is at your service.** Entry point of the UI.

```bash
gideon --ui                 # or: python3 src/gideon/ui/tray.py
gideon --ui --health        # one text snapshot, no GUI; exit 1 if offline
gideon --ui --no-hud        # tray icon and health panel only
gideon --ui --no-x11        # stay on the native backend
```

## What it guarantees, in order of importance

1. **It exists only when Gideon does.** The icon reflects a live subscription to the control
   socket. Daemon gone, killed or crash-looping — the icon goes red and struck through within
   a second or two, on its own. It is never a static "installed" badge.
2. **It shows the state** — ready / listening / thinking / speaking / follow-up — as colour,
   tooltip, menu header and, via `hud.py`, on screen.
3. **It answers "is everything working"** through the health panel, where every row is a
   measurement rather than an assumption.
4. **It lets you act**: arm push-to-talk (the same `wake` line the key sends), and
   start / stop / restart the daemon through `systemctl --user`.

## Mechanisms worth knowing

| Concern | How |
|---|---|
| **Single instance** | binds the *abstract* unix address `\0gideon-indicator-$UID`. Abstract, so the lock disappears with the process even on `SIGKILL` and can never be left behind stale the way a pidfile can |
| **Backend** | `want_x11()` → `reexec_on_x11()` sets `GDK_BACKEND=x11` and `execv`s itself, so the HUD can be placed and kept on top. The tray icon itself is D-Bus (StatusNotifierItem) and does not care |
| **Indicator library** | `load_indicator()` tries `AyatanaAppIndicator3` then `AppIndicator3`. Missing → prints the apt line and **still runs**, opening the health panel directly; the daemon is not affected either way |
| **Thread hand-off** | `StatusFeed` callbacks land on the feed thread and are bounced onto the GTK loop with `GLib.idle_add` |
| **First paint** | rendered before any snapshot arrives, as `offline` — a blank icon would imply everything is fine |

`--health` is deliberately GUI-free: it is what to run over ssh, in a script, or when the
tray itself is the thing that looks broken.
