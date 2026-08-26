# `src/gideon/ui/hud.py`

**The on-screen overlay: what Gideon is doing, and what he just heard.**

## Why it exists

A tray icon answers *is Gideon alive*. It does not answer the question you actually have
mid-sentence — **did he hear me, and as what**. That needs something in the middle of the
screen, up while you speak and gone the moment it stops being interesting.

## Three implementation facts

* **It is a GTK `POPUP` window**, which maps to an X11 override-redirect window — the only
  reliable way to get "exactly there, above everything, never stealing the keyboard". A
  normal window would be placed, stacked and focused at the window manager's discretion, and
  focus theft mid-typing would make the feature hostile.
* **It therefore wants the X11 backend.** GNOME's Mutter implements no layer-shell protocol,
  so under a native Wayland backend a client cannot position itself or stay on top.
  `tray.py` re-execs onto XWayland for this reason. Without XWayland the HUD still runs; it
  just appears wherever the compositor decides.

* **The window is transparent; the card is a widget.** `set_app_paintable(True)` tells GTK
  the application draws its own background, so CSS on the *window* is never painted — text
  would sit directly on whatever is behind it and be unreadable over a white page or a photo.
  Every visible pixel therefore belongs to an opaque `#hud-card` box inside the window, with
  an inset `#hud-body` panel behind the words so the transcript reads as a quoted block.

An RGBA visual is required for the rounded corners. Without one the HUD stops being
app-paintable and lets GTK draw the window, losing the corners — a square HUD is fine, the
black rectangle you would otherwise get around them is not.

## Only turns addressed to Gideon

The daemon transcribes **every** utterance in the room — that is how wake detection works
here: Whisper runs first, and the wake phrase is matched against the transcript. Rendering
all of it would put every passing conversation on screen and turn the HUD into surveillance
furniture. So `_update_engagement()` decides whether the current turn is Gideon's, and only
those are shown.

The catch is that *"is this for me"* is not known until Whisper finishes, which is **after**
`listening` and `thinking` have already been published. Rather than guess, the HUD stays
hidden through that gap and appears when the transcript arrives:

| Situation | HUD |
|---|---|
| Someone talking nearby, Gideon idle | hidden the whole way through — `listening`, `thinking`, and the `ignored` transcript |
| "Hey Gideon, …" | appears the moment the transcript comes back as `wake`, with the text and then the reply |
| Push-to-talk pressed (`armed`) | appears **immediately**, before you speak — Gideon is committed to listening and instant feedback is the point |
| Inside the follow-up window | same: `listening` is shown, because every utterance there is a query |
| Daemon gone | "Gideon is not running" plus the reason from `feed.py` |

The tradeoff: saying the wake phrase from cold gives no "Listening…" feedback until Whisper
rules, because the daemon genuinely does not know yet. The key and the follow-up window are
the two cases where it does.

## `apply(snapshot)` is the only entry point

Everything is rendered from one call per snapshot, so the HUD **cannot drift out of step**
with the daemon: there is no local state machine to get stuck in.

## Lingering and animation

An engaged turn holds the HUD open; resting starts a `LINGER_S` (3 s) countdown. A turn that
Whisper rules was *not* ours withdraws immediately instead — nothing on screen is worth
reading. The orb's halo amplitude
eases toward zero in resting states and the animation timer then **stops itself**, so an idle
Gideon neither pulses in the corner of your eye nor burns CPU.

`flash(message, state, seconds)` shows a one-off message; the tray uses it to confirm its own
menu actions.
