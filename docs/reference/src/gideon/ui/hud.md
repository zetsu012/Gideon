# `src/gideon/ui/hud.py`

**The on-screen overlay: a chat thread of the turn Gideon is handling.**

```
┌──────────────────────────────────────────────┐
│  ◉  LISTENING            no wake phrase …    │
│                        “what time is it” ◄── │   you, right, blue
│  ──► ••• → “Just past three.”                │   Gideon, left, grey
└──────────────────────────────────────────────┘
```

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
  Every visible pixel therefore belongs to an opaque `#hud-card` box inside the window: a
  header row (state glyph, state name, and a one-line hint on the right) above a vertical
  stack of bubbles.

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
| Daemon gone | a single system bubble, "Gideon is not running", plus the reason from `feed.py` when it says something beyond that |

The tradeoff: saying the wake phrase from cold gives no "Listening…" feedback until Whisper
rules, because the daemon genuinely does not know yet. The key and the follow-up window are
the two cases where it does.

## The thread

`MAX_BUBBLES` is 3: one exchange plus the previous question, which is as much history as is
useful mid-conversation. This is an overlay, not a transcript window. The oldest bubble is
destroyed when a fourth arrives, and the whole thread is dropped when the HUD hides, so each
appearance starts clean.

Both bubbles of a turn are created **before** their text exists:

| Moment | What appears |
|---|---|
| Gideon is committed to listening | your bubble, showing `•••` |
| Whisper rules on the segment | the transcript **streams into that same bubble** — two bubbles for one sentence would read as two sentences |
| `thinking` / `speaking` | Gideon's bubble, showing `•••` |
| the reply lands | it streams into that already-laid-out bubble, so the thread does not shove upwards as it fills |

## `apply(snapshot)` is the only entry point

Everything is rendered from one call per snapshot, so the HUD **cannot drift out of step**
with the daemon: there is no local state machine to get stuck in.

What it *does* keep is a little **conversation** memory — which bubble belongs to the turn in
progress — because a chat thread is by definition the thing one snapshot cannot describe. Two
rules make that memory safe:

* **A turn ends when a new utterance begins**, not only when the state goes to rest. The
  follow-up window stays in an ACTIVE state *across* turns, so without this the second
  question would stream into the first question's bubble.
* **`reply` is sticky in the daemon's snapshot** — it still holds the last answer while the
  next question is being transcribed. So a reply is streamed only into a bubble this turn
  created, and only once it differs from what was on screen when the turn began *or* the state
  has reached `speaking`. A plain "has it changed" test would both resurrect the previous
  answer at the start of a turn and leave a repeated question stuck on the placeholder — the
  second is why `thread_check()` in `tray.py` asks the same question twice.

Any update the HUD misses therefore costs one turn's bubbles and nothing beyond it.

## Lingering and animation

An engaged turn holds the HUD open; resting starts a `LINGER_S` (3.5 s) countdown. A turn that
Whisper rules was *not* ours withdraws immediately instead — nothing on screen is worth
reading; the thread is cleared on the way out. The state glyph's `level`
eases toward zero in resting states and the animation timer then **stops itself**, so an idle
Gideon neither pulses in the corner of your eye nor burns CPU. The per-bubble animations live
in [bubble.md](bubble.md).

The header's hint line prefers what Gideon is *doing* ("transcribing and answering") over
what the window is ("no wake phrase needed"): the first is news, the second is standing
context and only earns the line while he is waiting on you.

`flash(message, state, seconds)` replaces the thread with one system bubble; the tray uses it
to confirm its own menu actions.

`gideon --ui --demo` replays a scripted conversation through the HUD at conversational speed
with no daemon running — the animations are the point of this file and can only be watched,
not asserted.
