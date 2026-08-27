"""One turn of the conversation, drawn as a chat bubble.

The HUD used to be a single line of text that was replaced in place. That is
cheap to draw and impossible to read: a line that silently becomes a different
line gives you no way to tell "he heard me and is answering" from "he heard
something else". A bubble per turn fixes that by making the conversation
*additive* - what you said stays on screen while the reply arrives beneath it.

Two animations live here, and both exist for a reason rather than for polish:

  * **Entry** - a bubble slides up and fades in over ~200 ms (`Gtk.Revealer` for
    the slide, `set_opacity` for the fade, because GTK 3 revealers cannot do
    both). Appearing instantly reads as a flicker; the slide tells the eye where
    the new thing came from.
  * **Streaming** - text is revealed a few characters at a time rather than
    pasted whole. Whisper hands the daemon a *finished* transcript, so this is
    not real token streaming and does not pretend to be a progress bar; it is
    there because a growing line looks like speech being heard, and because
    reading starts before the sentence has finished landing.

Nothing in this module knows about the daemon. It is fed strings.
"""
from __future__ import annotations
import math, time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango                # noqa: E402

#: Entry animation, and the frame interval every tween here runs at (~60 fps).
ENTER_MS = 220
FRAME_MS = 16

#: Characters revealed per frame is `remaining / DIVISOR + FLOOR`, so a long
#: reply does not take proportionally longer to finish than a short one - it
#: starts fast and eases out, which is what reading wants.
STREAM_DIVISOR, STREAM_FLOOR = 14.0, 1.0

YOU, GIDEON, SYSTEM = "you", "gideon", "system"

#: The placeholder glyph. A bullet rather than a middle dot because it sits at
#: mid-height, so the empty bubble does not look bottom-heavy next to a full one.
DOT = "\u2022"

CSS = b"""
.bubble {
  border-radius: 16px;
  padding: 9px 14px;
  font-size: 15px;
}
.bubble-you {
  background-color: #2f6df6;
  color: #ffffff;
  border-bottom-right-radius: 5px;
}
.bubble-gideon {
  background-color: rgba(255, 255, 255, 0.09);
  color: #eef0f6;
  border-bottom-left-radius: 5px;
}
.bubble-system {
  background-color: rgba(255, 255, 255, 0.05);
  color: rgba(238, 240, 246, 0.72);
  font-size: 14px;
  border-radius: 12px;
}
"""


class Bubble(Gtk.Revealer):
    """A single bubble. `stream()` sets what it should eventually say."""

    def __init__(self, who: str, max_chars: int = 42):
        super().__init__()
        self.who = who
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.set_transition_duration(ENTER_MS)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(row)

        self.label = Gtk.Label(xalign=0.0)
        self.label.set_line_wrap(True)
        self.label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.label.set_max_width_chars(max_chars)
        self.label.set_lines(4)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.label.set_selectable(False)

        ctx = self.label.get_style_context()
        ctx.add_class("bubble")
        ctx.add_class("bubble-%s" % who)
        # A bubble hugs its text; the row's alignment is what puts "you" on the
        # right and Gideon on the left. Letting the label fill the row instead
        # would give every turn the same width and lose the chat shape.
        if who == YOU:
            row.pack_end(self.label, False, False, 0)
            self.label.set_xalign(1.0)
        else:
            row.pack_start(self.label, False, False, 0)

        self._target = ""
        self._shown = 0
        self._stream = None
        self._dots = None                 # "typing" placeholder animation
        self._t0 = time.time()
        self.set_opacity(0.0)
        self._fade = GLib.timeout_add(FRAME_MS, self._tick_fade)

    # -- entry -------------------------------------------------------------
    def enter(self) -> None:
        """Show the bubble and run its entry animation."""
        self.show_all()
        self.set_reveal_child(True)

    def _tick_fade(self) -> bool:
        k = min(1.0, (time.time() - self._t0) / (ENTER_MS / 1000.0))
        self.set_opacity(k * k * (3 - 2 * k))            # smoothstep
        if k >= 1.0:
            self._fade = None
            return False
        return True

    # -- content -----------------------------------------------------------
    def stream(self, text: str) -> None:
        """Reveal `text` progressively. Extends smoothly if `text` grows."""
        if text == self._target:
            return
        self.stop_typing()
        if not text.startswith(self._target[:self._shown]):
            self._shown = 0               # a correction, not a continuation
        self._target = text
        if self._stream is None:
            self._stream = GLib.timeout_add(FRAME_MS, self._tick_stream)
        self._tick_stream()

    def _tick_stream(self) -> bool:
        remaining = len(self._target) - self._shown
        if remaining <= 0:
            self.label.set_text(self._target)
            self._stream = None
            return False
        self._shown += max(1, int(remaining / STREAM_DIVISOR + STREAM_FLOOR))
        self.label.set_text(self._target[:self._shown])
        return True

    def set_now(self, text: str) -> None:
        """Set text with no animation (for placeholders and errors)."""
        self.stop_typing()
        self._stream, self._target, self._shown = None, text, len(text)
        self.label.set_text(text)

    @property
    def text(self) -> str:
        return self._target

    # -- the "…" placeholder ----------------------------------------------
    def start_typing(self) -> None:
        """Animate a three-dot placeholder until real text arrives.

        This is the honest thing to show between "Gideon is thinking" and the
        reply existing: the bubble is already on screen so the layout does not
        jump when the words land, but it claims nothing about what they are.
        """
        if self._dots is not None or self._target:
            return
        self._dot_phase = 0
        self.label.set_text(DOT)
        self._dots = GLib.timeout_add(260, self._tick_dots)

    def _tick_dots(self) -> bool:
        self._dot_phase = (self._dot_phase + 1) % 3
        self.label.set_text(DOT * (self._dot_phase + 1))
        return True

    def stop_typing(self) -> None:
        if self._dots is not None:
            GLib.source_remove(self._dots)
            self._dots = None

    def destroy(self) -> None:                              # noqa: D102
        self.stop_typing()
        for src in (self._stream, self._fade):
            if src is not None:
                GLib.source_remove(src)
        self._stream = self._fade = None
        super().destroy()


class Pulse(Gtk.DrawingArea):
    """The state glyph beside the state name.

    One widget, four behaviours, because the state word alone is easy to miss in
    peripheral vision and the movement is what actually catches the eye:
    listening draws level bars, thinking a rotating arc, speaking expanding
    rings, and everything else a still dot. `level` eases to zero in the resting
    states so the HUD stops moving instead of pulsing forever in the corner.
    """

    SIZE = 22

    def __init__(self, accent_of):
        super().__init__()
        self.accent_of = accent_of                          # () -> (r, g, b)
        self.set_size_request(self.SIZE, self.SIZE)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)
        self.state = ""
        self.level = 0.0
        self.phase = 0.0

    def _draw(self, _area, cr) -> bool:
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cx, cy = w / 2, h / 2
        r, g, b = self.accent_of()
        cr.set_line_cap(1)                                  # round
        kind = self.state

        if kind == "listening" and self.level > 0.02:
            cr.set_line_width(2.6)
            cr.set_source_rgba(r, g, b, 0.55 + 0.45 * self.level)
            for i in range(3):
                mag = 0.30 + 0.70 * abs(math.sin(self.phase * 1.7 + i * 1.05))
                half = (h * 0.34) * mag * self.level
                x = cx + (i - 1) * 5.2
                cr.move_to(x, cy - half); cr.line_to(x, cy + half); cr.stroke()
            return False

        if kind == "thinking" and self.level > 0.02:
            cr.set_line_width(2.6)
            cr.set_source_rgba(r, g, b, 0.30)
            cr.arc(cx, cy, w * 0.30, 0, 2 * math.pi); cr.stroke()
            cr.set_source_rgba(r, g, b, 0.95)
            cr.arc(cx, cy, w * 0.30, self.phase, self.phase + 1.9); cr.stroke()
            return False

        if kind == "speaking" and self.level > 0.02:
            for i in range(2):
                k = ((self.phase * 0.55 + i * 0.5) % 1.0)
                cr.set_source_rgba(r, g, b, (1.0 - k) * 0.55 * self.level)
                cr.set_line_width(2.0)
                cr.arc(cx, cy, w * (0.16 + 0.30 * k), 0, 2 * math.pi)
                cr.stroke()

        # The resting dot, also the core the rings above expand from.
        cr.set_source_rgba(r, g, b, 0.35 + 0.65 * max(0.35, self.level))
        cr.arc(cx, cy, w * 0.155, 0, 2 * math.pi)
        cr.fill()
        return False
