# `src/gideon/ui/bubble.py`

**One turn of the conversation, drawn as a chat bubble — plus the state glyph.**

## Why it exists

The HUD used to be a single line of text replaced in place. That is cheap to draw and
impossible to read: a line that silently becomes a different line gives you no way to tell
*he heard me and is answering* from *he heard something else*. A bubble per turn makes the
conversation **additive** — what you said stays on screen while the reply arrives beneath it.

Nothing here knows about the daemon. It is fed strings by `hud.py`.

## The two animations, and why each is not decoration

| Animation | What it is | Why |
|---|---|---|
| **Entry** | `Gtk.Revealer` slide-up (~220 ms) plus an eased `set_opacity` fade | GTK 3 revealers do slide *or* crossfade, not both, so the fade is a hand-run tween. Appearing instantly reads as a flicker; the slide tells the eye where the new thing came from. |
| **Streaming** | `stream(text)` reveals `remaining / 14 + 1` characters per 16 ms frame | Whisper hands the daemon a **finished** transcript, so this is not token streaming and does not pretend to be progress. A growing line looks like speech being heard, and reading starts before the sentence lands. The rate is proportional, so a long reply starts fast and eases out instead of taking proportionally longer. |

`stream()` is safe to call repeatedly with the same or a growing string — it continues from
where it is. A string that is *not* an extension of what is shown resets the reveal, because
that is a correction rather than a continuation.

`set_now(text)` sets text with no animation, for placeholders and error notes.

## The `•••` placeholder

`start_typing()` animates one to three bullets until real text arrives. It is the honest
thing to show between "Gideon is thinking" and the reply existing: the bubble is already on
screen so the layout does not jump when the words land, but it claims nothing about what they
are. A bullet rather than a middle dot, so an empty bubble is not bottom-heavy beside a full
one; `hud.py`'s self-check matches on `bubble.DOT` rather than a literal.

A bubble **hugs its text** — the row's alignment (`pack_end` for you, `pack_start` for
Gideon) is what produces the chat shape. Letting the label fill the row would give every turn
the same width and lose it.

`destroy()` removes every timer it owns. Bubbles are evicted as the thread grows, so a leaked
`GLib` source here would accumulate for the life of the indicator.

## `Pulse` — the state glyph

One `DrawingArea` beside the state name, four behaviours, because the word alone is easy to
miss in peripheral vision and movement is what catches the eye:

| State | Drawn as |
|---|---|
| `listening` | three level bars, out of phase |
| `thinking` | a rotating arc on a dim ring |
| `speaking` | rings expanding out of the dot |
| anything else | a still dot |

`level` is eased toward zero by `hud.py` in the resting states, and the HUD's animation timer
then stops itself — an idle Gideon neither pulses in the corner of your eye nor burns CPU.
Colour comes from `theme.accent()` through a callable, so the glyph can never disagree with
the tray icon about which state is which colour.
