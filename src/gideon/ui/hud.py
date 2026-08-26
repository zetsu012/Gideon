"""The on-screen overlay: what Gideon is doing, and what he just heard.

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

Everything is drawn from one `apply()` call per snapshot, so the HUD can never
drift out of step with the daemon: there is no local state machine to get stuck.
"""
from __future__ import annotations
import math, sys, time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango           # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feed, theme                                        # noqa: E402

WIDTH, MARGIN_BOTTOM = 620, 96
#: Room around the card for its drop shadow, which is drawn outside the widget.
SHADOW = 14
#: How long the HUD lingers after Gideon goes back to resting. Long enough to
#: read the last exchange, short enough not to sit on top of your work.
LINGER_S = 3.0

CSS = b"""
#hud { background-color: transparent; }

/* Everything visible is this card. It is opaque enough to read against a white
   browser page or a photo wallpaper - transparency here would be a nice effect
   that costs the HUD its only job. */
#hud-card {
  background-color: rgba(16, 16, 22, 0.97);
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.13);
  box-shadow: 0 8px 26px rgba(0, 0, 0, 0.55);
}
/* An inset panel behind the words themselves, so the transcript reads as a
   quoted block rather than as floating text. */
#hud-body {
  background-color: rgba(255, 255, 255, 0.07);
  border-radius: 12px;
  padding: 10px 14px;
}
#hud-state { font-size: 12px; font-weight: 700; letter-spacing: 1.2px; }
#hud-text  { font-size: 17px; color: #f4f4f7; }
#hud-reply { font-size: 15px; color: rgba(244, 244, 247, 0.86); }
"""


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

        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        card.set_name("hud-card")
        for setter in ("set_margin_top", "set_margin_bottom",
                       "set_margin_start", "set_margin_end"):
            getattr(card, setter)(SHADOW)     # let the shadow fall inside the window
        self.add(card)

        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        inner.set_margin_top(18); inner.set_margin_bottom(18)
        inner.set_margin_start(20); inner.set_margin_end(20)
        card.pack_start(inner, True, True, 0)

        self.orb = Gtk.DrawingArea()
        self.orb.set_size_request(46, 46)
        self.orb.set_valign(Gtk.Align.CENTER)
        self.orb.connect("draw", self._draw_orb)
        inner.pack_start(self.orb, False, False, 0)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        col.set_valign(Gtk.Align.CENTER)
        inner.pack_start(col, True, True, 0)

        self.state_label = Gtk.Label(xalign=0.0)
        self.state_label.set_name("hud-state")
        col.pack_start(self.state_label, False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        body.set_name("hud-body")
        col.pack_start(body, False, False, 0)

        self.text_label = Gtk.Label(xalign=0.0)
        self.text_label.set_name("hud-text")
        self.text_label.set_line_wrap(True)
        self.text_label.set_lines(2)
        self.text_label.set_ellipsize(Pango.EllipsizeMode.END)
        body.pack_start(self.text_label, False, False, 0)

        self.reply_label = Gtk.Label(xalign=0.0)
        self.reply_label.set_name("hud-reply")
        self.reply_label.set_line_wrap(True)
        self.reply_label.set_lines(3)
        self.reply_label.set_ellipsize(Pango.EllipsizeMode.END)
        # Managed by hand so an empty reply reserves no height and the card
        # shrinks to one line while Gideon is still listening.
        self.reply_label.set_no_show_all(True)
        body.pack_start(self.reply_label, False, False, 0)

        self._state = feed.OFFLINE
        self._phase = 0.0
        self._level = 0.0          # eased "how animated should the orb be"
        self._anim = None
        self._hide_at = 0.0
        self._engaged = False      # is this turn addressed to Gideon? (see below)
        self._invited = False      # key pressed, or follow-up window open
        self._last_heard_at = 0.0
        self._hide_timer = GLib.timeout_add(250, self._maybe_hide)

    # -- painting ----------------------------------------------------------
    def _draw_orb(self, area, cr):
        w = area.get_allocated_width()
        h = area.get_allocated_height()
        cx, cy = w / 2, h / 2
        r, g, b = theme.accent(self._state)

        # Breathing halo. Its amplitude follows `_level`, which eases toward 0
        # in the resting states, so the HUD settles instead of pulsing forever
        # in the corner of your eye.
        if self._level > 0.01:
            for i, (scale, alpha) in enumerate(((1.00, 0.16), (0.78, 0.24))):
                pulse = 1.0 + 0.18 * self._level * math.sin(self._phase + i * 0.9)
                cr.set_source_rgba(r, g, b, alpha * self._level)
                cr.arc(cx, cy, (w / 2) * scale * pulse, 0, 2 * math.pi)
                cr.fill()

        cr.set_source_rgb(r, g, b)
        cr.arc(cx, cy, w / 2 * 0.42, 0, 2 * math.pi)
        cr.fill()
        return False

    def _animate(self) -> bool:
        target = 1.0 if self._state in feed.ACTIVE else 0.0
        self._level += (target - self._level) * 0.12
        self._phase += 0.16
        self.orb.queue_draw()
        if target == 0.0 and self._level < 0.01:
            self._level, self._anim = 0.0, None
            self.orb.queue_draw()
            return False                      # nothing moving: stop burning CPU
        return True

    def _ensure_animating(self) -> None:
        if self._anim is None:
            self._anim = GLib.timeout_add(33, self._animate)

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
        self._state = state
        self._update_engagement(snap)
        self.state_label.set_markup(
            '<span foreground="%s">%s</span>' % (theme.hex_of(state), theme.label(state).upper()))

        text = snap.get("transcript", "")
        show_transcript = self._engaged and snap.get("transcript_kind") in ("wake", "key", "follow")

        if state == feed.OFFLINE:
            self.text_label.set_text("Gideon is not running")
            self._set_reply(snap.get("detail", ""))
        elif state == feed.LISTENING or not show_transcript:
            # Whisper has not ruled yet, so there is nothing true to print.
            # Saying so beats leaving the previous utterance on screen, which
            # would read as though it had just been heard again.
            self.text_label.set_text(
                "Listening…" if state == feed.LISTENING else
                "One moment…" if state == feed.THINKING else
                "Go ahead — no wake phrase needed")
            self._set_reply("")
        else:
            self.text_label.set_text("“%s”" % text)
            self._set_reply(snap.get("reply", ""))

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
        self._ensure_animating()

    def _set_reply(self, text: str) -> None:
        self.reply_label.set_text(text)
        self.reply_label.set_visible(bool(text))

    def _show(self) -> None:
        if not self.get_visible():
            self.show_all()
        self.resize(WIDTH, 1)          # shrink to the content's natural height
        self._place()
        self.present()

    def _maybe_hide(self) -> bool:
        if self._hide_at and time.time() >= self._hide_at:
            self._hide_at = 0.0
            self.hide()
        return True

    def flash(self, message: str, state: str = feed.IDLE, seconds: float = 2.0) -> None:
        """Show a one-off message (used by the tray's own actions)."""
        self._state = state
        self.state_label.set_markup(
            '<span foreground="%s">%s</span>' % (theme.hex_of(state), theme.label(state).upper()))
        self.text_label.set_text(message)
        self._set_reply("")
        self._show()
        self._ensure_animating()
        self._hide_at = time.time() + seconds
