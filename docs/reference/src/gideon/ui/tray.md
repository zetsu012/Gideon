# `src/gideon/ui/tray.py`

**The tray indicator: the proof that the daemon is at your service.** Entry point of the UI.

```bash
gideon --ui                 # or: python3 src/gideon/ui/tray.py
gideon --ui --health        # one text snapshot, no GUI; exit 1 if offline
gideon --ui --self-check    # assert which turns the HUD shows and what the bubbles say
gideon --ui --demo          # replay a conversation through the HUD; no daemon needed
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


## `--self-check`

`gideon --selftest` runs on the vendored interpreter and cannot import GTK, so the UI needs
its own check. What it asserts is not that widgets construct — it is the one rule with real
consequences: **which turns reach the screen**. Both directions are bugs the user notices
within a minute: a HUD that stays dark when the key is pressed, or one that puts every
passing conversation on the desktop.

`SELF_CHECK` is a scripted conversation — key press, keyed query, follow-up, a neighbour
talking, a wake phrase from cold, the daemon dying — each with the visibility it must
produce. Add a row when you change the engagement rules in `hud.py`.

`THREAD_CHECK` is the second half, and covers what the HUD became when it grew bubbles:
*visible* is no longer the whole invariant — which bubbles a turn produced, and what they
finally say, is what the user reads. It plays one complete conversation and checks the thread
after each step, pinning down three rules from `hud.py`: your bubble is created while Gideon
is still listening and the transcript streams into **that** bubble rather than a second one;
Gideon's bubble appears empty while he thinks and fills in when the reply lands; and asking
the same question twice still fills its own bubble, because the daemon's `reply` field is
sticky and a naive "has it changed" test leaves it on the placeholder. An expected text of
`None` means "the animated placeholder", whose exact frame depends on when the check looked.

`_settle()` pumps the GTK loop for a beat before either half looks. Every animation here is a
timer and withdrawal is deferred to a 250 ms one, so asking straight after `apply()` reports
every hide as a failure and every streamed bubble as empty — the HUD is mid-animation, not
wrong.

## `--demo`

The animations are the point of the HUD and cannot be asserted, only watched. `--demo`
replays `THREAD_CHECK`'s conversation at conversational speed against no daemon, so "does it
feel right" does not require a running Gideon and a wake phrase that lands.
