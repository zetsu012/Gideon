"""The on-screen overlay: a chat thread of the turn Gideon is handling.

    ┌──────────────────────────────────────────────┐
    │  ◉  LISTENING                                │
    │                        “what time is it” ◄── │   you, right, blue
    │  ──► ··· / “Just past three.”                │   Gideon, left, grey
    └──────────────────────────────────────────────┘

A tray icon answers "is Gideon alive". It does not answer the question you
actually have mid-sentence - *did he hear me, and as what*. That needs something
in the middle of the screen, up while you speak and gone the moment it stops
being interesting. Hence a HUD rather than a window: no title bar, no taskbar
entry, never focused, and it disappears on its own.

Three implementation facts worth knowing before editing this file:

  * **It is a GTK POPUP window.** That maps to an X11 override-redirect window,
    which is the only reliable way to get "exactly there, above everything, and
    never stealing the keyboard" - a normal window would be placed, stacked and
    focused at the window manager's discretion, and focus theft mid-typing would
    make the whole feature hostile.
  * **It therefore wants the X11 backend.** GNOME's Mutter does not implement
    the layer-shell protocol, so under a native Wayland backend a client simply
    cannot position itself or stay on top. `tray.py` selects XWayland for this
    reason; on Wayland-without-XWayland the HUD still runs, it just appears
    wherever the compositor decides.
  * **The window is transparent; the card is a widget.** `set_app_paintable(True)`
    tells GTK the application draws its own background, so CSS on the window
    itself is never painted - text would then sit directly on whatever is behind
    it and be unreadable over anything busy. So the window stays empty and every
    pixel of the HUD is drawn by an opaque card widget inside it.

Everything is driven from one `apply()` call per snapshot, so the HUD can never
drift out of step with the daemon: there is no local state machine to get stuck.
What it *does* keep is a small amount of *conversation* memory - which bubble
belongs to the turn in progress - because a chat thread is by definition the
thing a single snapshot cannot describe. That memory is derived only from
`transcript_at` and `reply` changing, and `_reset_thread()` throws all of it away
whenever a turn ends, so a missed update costs one turn's bubbles and nothing
more. See `bubble.py` for the animations.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk                  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bubble, feed, theme                                # noqa: E402
from bubble import Bubble, Pulse                          # noqa: E402

WIDTH, MARGIN_BOTTOM = 560, 96
#: Room around the card for its drop shadow, which is drawn outside the widget.
SHADOW = 14
#: How long the HUD lingers after Gideon goes back to resting. Long enough to
#: read the last exchange, short enough not to sit on top of your work.
LINGER_S = 3.5
#: Bubbles kept on screen. Two is one exchange; the third is the previous
#: question, which is exactly as much history as is useful mid-conversation and
#: no more - this is an overlay, not a transcript window.
MAX_BUBBLES = 3

CSS = b"""
#hud { background-color: transparent; }

/* Everything visible is this card. It is opaque enough to read against a white
   browser page or a photo wallpaper - transparency here would be a nice effect
   that costs the HUD its only job. */
#hud-card {
  background-color: rgba(15, 15, 20, 0.96);
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.11);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.55);
}
#hud-state {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.4px;
}
#hud-hint {
  font-size: 11px;
  color: rgba(238, 240, 246, 0.38);
  letter-spacing: 0.4px;
}
""" + bubble.CSS


class Hud(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.set_name("hud")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_default_size(WIDTH, -1)
        self.set_size_request(WIDTH, -1)

        # Without an RGBA visual there is no transparency to have: the window
        # would composite black around the card's rounded corners. In that case
        # let GTK paint the window itself and lose the corners instead - a
        # square HUD is fine, a black rectangle around it is not.
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        self.set_app_paintable(visual is not None)
        if visual is not None:
            self.set_visual(visual)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.set_name("hud-card")
        for setter in ("set_margin_top", "set_margin_bottom",
                       "set_margin_start", "set_margin_end"):
            getattr(card, setter)(SHADOW)     # let the shadow fall inside the window
        self.add(card)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        inner.set_margin_top(14); inner.set_margin_bottom(16)
        inner.set_margin_start(18); inner.set_margin_end(18)
        card.pack_start(inner, True, True, 0)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        inner.pack_start(header, False, False, 0)

        self.pulse = Pulse(lambda: theme.accent(self._state))
        header.pack_start(self.pulse, False, False, 0)

        self.state_label = Gtk.Label(xalign=0.0)
        self.state_label.set_name("hud-state")
        header.pack_start(self.state_label, False, False, 0)

        self.hint_label = Gtk.Label(xalign=1.0)
        self.hint_label.set_name("hud-hint")
        header.pack_end(self.hint_label, False, False, 0)

        #: The bubbles, oldest first.
        self.thread = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        inner.pack_start(self.thread, False, False, 0)

        self._state = feed.OFFLINE
        self._level = 0.0          # eased "how animated should the glyph be"
        self._anim = None
        self._hide_at = 0.0
        self._engaged = False      # is this turn addressed to Gideon? (see below)
        self._invited = False      # key pressed, or follow-up window open
        self._last_heard_at = 0.0
        self._bubbles: list[Bubble] = []
        self._said = None          # the "you" bubble of the turn in progress
        self._replied = None       # the "gideon" bubble of the turn in progress
        self._reply_base = ""      # the reply already on screen when this turn began
        self._hide_timer = GLib.timeout_add(250, self._maybe_hide)

    # -- animation ---------------------------------------------------------
    def _animate(self) -> bool:
        target = 1.0 if self._state in feed.ACTIVE else 0.0
        self._level += (target - self._level) * 0.14
        self.pulse.level = self._level
        self.pulse.state = self._state
        self.pulse.phase += 0.14
        self.pulse.queue_draw()
        if target == 0.0 and self._level < 0.01:
            self._level = self.pulse.level = 0.0
            self._anim = None
            self.pulse.queue_draw()
            return False                      # nothing moving: stop burning CPU
        return True

    def _ensure_animating(self) -> None:
        if self._anim is None:
            self._anim = GLib.timeout_add(bubble.FRAME_MS * 2, self._animate)

    # -- placement ---------------------------------------------------------
    def _place(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        monitor = (display.get_monitor_at_window(self.get_window())
                   if self.get_window() else None) or display.get_monitor(0)
        area = monitor.get_workarea()
        width, height = self.get_size()
        self.move(area.x + (area.width - width) // 2,
                  area.y + area.height - height - MARGIN_BOTTOM)

    # -- the thread --------------------------------------------------------
    def _add(self, who: str) -> Bubble:
        """Append a bubble, evicting the oldest once the thread is full."""
        b = Bubble(who)
        self._bubbles.append(b)
        self.thread.pack_start(b, False, False, 0)
        while len(self._bubbles) > MAX_BUBBLES:
            old = self._bubbles.pop(0)
            if old is self._said:
                self._said = None
            if old is self._replied:
                self._replied = None
            old.destroy()
        if self.get_visible():
            b.enter()
        return b

    def _reset_thread(self) -> None:
        for b in self._bubbles:
            b.destroy()
        self._bubbles.clear()
        self._said = self._replied = None

    def _end_turn(self, reply: str = "") -> None:
        """The turn is over: the next thing heard starts new bubbles.

        `reply` is the answer this turn ended with. It is remembered because the
        daemon's `reply` field is sticky - it still holds the last answer while
        the *next* question is being transcribed - so the only way to tell "this
        reply is mine" from "this reply is the previous turn's, still there" is
        to know what it was when the turn began.
        """
        self._said = self._replied = None
        self._reply_base = reply

    # -- is this turn ours? ------------------------------------------------
    def _update_engagement(self, snap: dict) -> None:
        """Decide whether the current turn is addressed to Gideon.

        The daemon transcribes *every* utterance in the room, because that is how
        wake detection works here - Whisper runs first and the wake phrase is
        matched against the transcript. Showing all of it would put every passing
        conversation on screen and turn the HUD into surveillance furniture. So
        the HUD renders only turns Gideon is actually acting on.

        The catch is that "is this for me" is not known until Whisper finishes,
        which is *after* the listening and thinking states have already been
        published. Rather than guess, the HUD stays hidden through that gap and
        appears when the transcript arrives - unless the user pressed the key or
        is inside the follow-up window, where Gideon is committed to listening
        and immediate feedback is the whole point.
        """
        state = snap.get("state")
        heard_at = snap.get("transcript_at", 0.0)
        kind = snap.get("transcript_kind", "")
        invited = bool(snap.get("armed")) or snap.get("follow_for", 0) > 0
        self._invited = invited

        if state == feed.LISTENING and heard_at <= self._last_heard_at:
            # A new utterance has begun and nothing has been transcribed for it
            # yet: this turn is ours only if we invited it.
            self._engaged = invited
        if heard_at > self._last_heard_at:
            # Whisper has ruled on this turn.
            self._last_heard_at = heard_at
            self._engaged = kind in ("wake", "key", "follow")
        elif invited:
            self._engaged = True
        if state in (feed.IDLE, feed.STARTING) and not invited:
            self._engaged = False

    # -- the only entry point ---------------------------------------------
    def apply(self, snap: dict) -> None:
        """Render one snapshot. Called for every daemon update."""
        state = snap.get("state", feed.OFFLINE)
        heard_at = snap.get("transcript_at", 0.0)
        fresh_transcript = heard_at > self._last_heard_at
        self._state = state
        self._update_engagement(snap)

        self.state_label.set_markup(
            '<span foreground="%s">%s</span>'
            % (theme.hex_of(state), theme.label(state).upper()))

        show_transcript = self._engaged and snap.get("transcript_kind") in (
            "wake", "key", "follow")

        if state == feed.OFFLINE:
            self._offline(snap)
        else:
            self._thread_for(snap, state, fresh_transcript, show_transcript)

        # `invited` matters on its own: pressing the key arms Gideon while he is
        # still idle - nothing has been said yet - and that is precisely the
        # moment the prompt needs to be on screen. Requiring an ACTIVE state
        # here made the key silent until the user had already started talking,
        # which is the wrong way round for the one gesture that exists to say
        # "listen to me now".
        wanted = state == feed.OFFLINE or (
            self._engaged and (state in feed.ACTIVE or self._invited))
        if wanted:
            self._hide_at = 0.0
            self._show()
        elif self.get_visible() and not self._hide_at:
            # Either the turn was not ours after all, or Gideon has gone back to
            # resting. Withdraw - immediately in the first case, since nothing
            # on screen is worth reading, and after a beat in the second.
            self._hide_at = time.time() + (LINGER_S if self._engaged else 0.0)
        if state not in feed.ACTIVE:
            self._end_turn(snap.get("reply", ""))
        self._ensure_animating()
        if self.get_visible():
            self._reflow()

    def _offline(self, snap: dict) -> None:
        detail = snap.get("detail", "")
        if len(self._bubbles) != 1 or self._bubbles[0].who != bubble.SYSTEM:
            self._reset_thread()
            self._add(bubble.SYSTEM)
        # `feed` explains a plain absence as "the daemon is not running", which
        # is the same sentence twice here; only a detail that says something new
        # (a stale socket, an unexpected errno) is worth the room.
        note = "" if detail in ("", "the daemon is not running") else " — %s" % detail
        self._bubbles[0].set_now("Gideon is not running" + note)
        self.hint_label.set_text("")

    def _thread_for(self, snap: dict, state: str,
                    fresh_transcript: bool, show_transcript: bool) -> None:
        """Grow the thread to match this snapshot."""
        if self._bubbles and self._bubbles[-1].who == bubble.SYSTEM:
            self._reset_thread()               # leaving an offline/flash message

        # What Gideon is doing wins over what the window is: "transcribing and
        # answering" is news, "no wake phrase needed" is standing context and
        # only worth the line while he is waiting on you.
        self.hint_label.set_text(
            theme.describe(state) if state in (feed.SPEAKING, feed.THINKING)
            else "no wake phrase needed" if self._invited
            else "")

        if not self._engaged:
            return

        # A new utterance while the previous turn's bubbles are still on screen
        # starts a new turn. Without this the follow-up window - which stays in
        # an ACTIVE state across turns, so nothing else ends the turn - would
        # stream the second question into the first question's bubble.
        if self._replied is not None and (
                fresh_transcript or (state == feed.LISTENING and not fresh_transcript)):
            self._end_turn(snap.get("reply", ""))

        # What was said. The bubble is created as soon as Gideon is committed to
        # listening, so it is on screen while you are still talking; the words
        # stream into that same bubble when Whisper rules on the segment. Two
        # bubbles for one sentence would read as two sentences.
        if state == feed.LISTENING and self._said is None and not fresh_transcript:
            self._said = self._add(bubble.YOU)
            self._said.start_typing()
        if fresh_transcript and show_transcript:
            text = snap.get("transcript", "")
            if self._said is None:
                self._said = self._add(bubble.YOU)
            self._said.stream(text)
        elif show_transcript and self._said is not None and not self._said.text:
            self._said.stream(snap.get("transcript", ""))

        # What Gideon answered. Same shape: the bubble appears while he is
        # thinking - as a "···" placeholder - so the reply streams into a bubble
        # that is already laid out instead of shoving the thread upwards.
        reply = snap.get("reply", "")
        if state in (feed.THINKING, feed.SPEAKING, feed.FOLLOWUP) and self._replied is None:
            self._replied = self._add(bubble.GIDEON)
            self._replied.start_typing()
        # `reply` is compared against the bubble's own text rather than against
        # the previous snapshot's: asking the same question twice produces the
        # same reply string, and a "has it changed" test would leave the second
        # turn's bubble stuck on the placeholder.
        # Streamed only into a bubble this turn already created, and compared
        # against that bubble's own text rather than against the previous
        # snapshot's reply: `reply` is sticky in the daemon's snapshot, so
        # "has it changed" would both resurrect the last turn's answer at the
        # start of this one and leave a repeated question stuck on the
        # placeholder.
        if reply and self._replied is not None and (
                reply != self._reply_base or state in (feed.SPEAKING, feed.FOLLOWUP)):
            self._replied.stream(reply)

    # -- window ------------------------------------------------------------
    def _show(self) -> None:
        first = not self.get_visible()
        if first:
            self.show_all()
        for b in self._bubbles:
            b.enter()                    # a no-op for bubbles already revealed
        self._reflow()

    def _reflow(self) -> None:
        self.resize(WIDTH, 1)            # shrink to the content's natural height
        self._place()
        if self.get_visible():
            self.present()

    def _maybe_hide(self) -> bool:
        if self._hide_at and time.time() >= self._hide_at:
            self._hide_at = 0.0
            self.hide()
            self._reset_thread()         # next appearance starts a clean thread
        return True

    def flash(self, message: str, state: str = feed.IDLE, seconds: float = 2.0) -> None:
        """Show a one-off message (used by the tray's own actions)."""
        self._state = state
        self.state_label.set_markup(
            '<span foreground="%s">%s</span>' % (theme.hex_of(state), theme.label(state).upper()))
        self.hint_label.set_text("")
        self._reset_thread()
        note = self._add(bubble.SYSTEM)
        note.set_now(message)
        self._show()
        self._ensure_animating()
        self._hide_at = time.time() + seconds
