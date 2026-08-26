"""The health panel: every part of Gideon, and whether it is actually working.

Opened from the tray. The design rule is that nothing in this window is a
constant: every row is either a fact the daemon published into its StatusBus, or
something this process just measured (a systemd unit's state, a socket file's
existence). A row that said "Microphone: OK" because a list in this file said so
would make the whole indicator worthless, so there is no such list - the rows
are generated from whatever the daemon reported, and a subsystem that never
reported is shown as unknown rather than fine.

Two sources, clearly separated in the window:

  * **Daemon** - mic, VAD, Whisper, Piper, the local brain, the control socket.
    Only available when the daemon is up; when it is down the section says so
    instead of showing stale green ticks.
  * **Session** - the systemd user units and the socket, checked from here, and
    therefore still meaningful precisely when the daemon is *not* answering.
"""
from __future__ import annotations
import subprocess, sys, time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango                # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feed, theme                                        # noqa: E402

UNITS = (("gideon.service", "Daemon unit", "the always-on process that owns the microphone"),
         ("gideon-ui.service", "Indicator unit", "this tray icon"),
         ("gideon-hotkey.service", "Push-to-talk unit", "the key listener; optional"))

OK, BAD, MEH = "#4dc77a", "#e05757", "#b8b8bf"


def unit_state(unit: str) -> tuple[str, str]:
    """(active-state, sub-state) for a systemd *user* unit; ('missing','') if absent."""
    try:
        out = subprocess.run(["systemctl", "--user", "show", unit,
                              "--property=ActiveState", "--property=SubState",
                              "--property=LoadState"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ("unknown", "")
    fields = dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
    if fields.get("LoadState") in ("not-found", "masked", None):
        return ("missing", fields.get("LoadState", ""))
    return (fields.get("ActiveState", "unknown"), fields.get("SubState", ""))


def _human_age(seconds: float) -> str:
    if seconds < 60:
        return "%ds" % int(seconds)
    if seconds < 3600:
        return "%dm %ds" % (int(seconds // 60), int(seconds % 60))
    return "%dh %dm" % (int(seconds // 3600), int((seconds % 3600) // 60))


class HealthPanel(Gtk.Window):
    """A window that re-measures itself whenever it is on screen."""

    def __init__(self, get_snapshot):
        super().__init__(title="Gideon — service health")
        self.get_snapshot = get_snapshot
        self.set_default_size(560, 620)
        self.set_icon_name("audio-input-microphone")
        # Closing must hide, not destroy: the tray keeps a single instance so
        # reopening is instant and never spawns a second window.
        self.connect("delete-event", lambda *_: (self.hide(), True)[1])

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(outer)

        self.header = Gtk.Label(xalign=0.0)
        self.header.set_margin_top(18)
        self.header.set_margin_start(20); self.header.set_margin_end(20)
        outer.pack_start(self.header, False, False, 0)

        self.subheader = Gtk.Label(xalign=0.0)
        self.subheader.set_margin_start(20); self.subheader.set_margin_end(20)
        self.subheader.set_margin_bottom(10)
        self.subheader.set_line_wrap(True)
        outer.pack_start(self.subheader, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(scroller, True, True, 0)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.rows.set_margin_start(20); self.rows.set_margin_end(20)
        self.rows.set_margin_bottom(16)
        scroller.add(self.rows)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_start(20); bar.set_margin_end(20); bar.set_margin_bottom(16)
        outer.pack_start(bar, False, False, 0)
        refresh = Gtk.Button(label="Re-check")
        refresh.connect("clicked", lambda *_: self.refresh())
        bar.pack_start(refresh, False, False, 0)
        logs = Gtk.Button(label="Copy log command")
        logs.connect("clicked", self._copy_log_command)
        bar.pack_start(logs, False, False, 0)
        self.hint = Gtk.Label(xalign=1.0)
        bar.pack_end(self.hint, True, True, 0)

        self._timer = None
        self.connect("show", self._on_show)
        self.connect("hide", self._on_hide)

    # -- lifecycle ---------------------------------------------------------
    def _on_show(self, *_):
        # The unit checks shell out, so they only run while someone is looking.
        self.refresh()
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(3, self._tick)

    def _on_hide(self, *_):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self) -> bool:
        self.refresh()
        return True

    def _copy_log_command(self, button):
        command = "journalctl --user -u gideon -f"
        Gtk.Clipboard.get_default(self.get_display()).set_text(command, -1)
        self.hint.set_markup('<span size="small" foreground="%s">copied: %s</span>'
                             % (MEH, GLib.markup_escape_text(command)))

    # -- rendering ---------------------------------------------------------
    def refresh(self) -> None:
        for child in self.rows.get_children():
            child.destroy()

        snap = self.get_snapshot() or {}
        online = bool(snap) and snap.get("state") not in (None, feed.OFFLINE)
        state = snap.get("state", feed.OFFLINE)

        self.header.set_markup(
            '<span size="x-large" weight="bold" foreground="%s">%s</span>'
            % (theme.hex_of(state), GLib.markup_escape_text(theme.label(state))))
        if online:
            self.subheader.set_markup(
                '<span foreground="%s">%s · up %s · pid %s · %d utterances, %d answered</span>'
                % (MEH, GLib.markup_escape_text(theme.describe(state)),
                   _human_age(snap.get("uptime", 0)), snap.get("pid", "?"),
                   snap.get("counters", {}).get("utterances", 0),
                   snap.get("counters", {}).get("replies", 0)))
        else:
            self.subheader.set_markup(
                '<span foreground="%s">Nothing is listening on the control socket. '
                'Gideon will not answer to "hey Gideon" or to the key.</span>' % BAD)

        self._section("Daemon", "reported by the running daemon")
        if online:
            health = snap.get("health", {})
            for key, (name, blurb) in theme.SUBSYSTEMS.items():
                entry = health.get(key)
                if entry is None:
                    self._row(name, None, "not reported yet", blurb)
                else:
                    self._row(name, entry.get("ok"), entry.get("detail", ""), blurb)
            for key, entry in health.items():         # anything added later
                if key not in theme.SUBSYSTEMS:
                    self._row(key, entry.get("ok"), entry.get("detail", ""), "")
            if snap.get("last_error"):
                self._row("Last error", False, snap["last_error"], "")
        else:
            self._row("Daemon", False, "not answering on %s" % feed.socket_path(),
                      "start it with: systemctl --user start gideon")

        self._section("This session", "measured from the desktop, right now")
        for unit, name, blurb in UNITS:
            active, sub = unit_state(unit)
            optional = unit != "gideon.service"
            ok = active == "active"
            detail = active if not sub else f"{active} ({sub})"
            if active == "missing" and optional:
                ok, detail = None, "not installed — optional"
            self._row(name, ok, detail, blurb)
        sock = feed.socket_path()
        self._row("Control socket", sock.exists(),
                  str(sock) if sock.exists() else "%s does not exist" % sock,
                  "how the key and this indicator reach the daemon")

        last = snap.get("transcript")
        if last:
            self._section("Last heard", "")
            age = _human_age(max(0.0, time.time() - snap.get("transcript_at", 0)))
            self._row("“%s”" % last, snap.get("transcript_kind") != "ignored",
                      "%s · %s ago" % (snap.get("transcript_kind", "?"), age),
                      snap.get("reply", ""))
        self.rows.show_all()

    def _section(self, title: str, blurb: str) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(18)
        label = Gtk.Label(xalign=0.0)
        label.set_markup('<span weight="bold">%s</span>%s'
                         % (GLib.markup_escape_text(title),
                            ('  <span size="small" foreground="%s">%s</span>'
                             % (MEH, GLib.markup_escape_text(blurb))) if blurb else ""))
        box.pack_start(label, False, False, 0)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 6)
        self.rows.pack_start(box, False, False, 0)

    def _row(self, name: str, ok: bool | None, detail: str, blurb: str) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_margin_top(4); row.set_margin_bottom(4)

        mark = Gtk.Label()
        colour = OK if ok else (BAD if ok is False else MEH)
        glyph = "●" if ok else ("✕" if ok is False else "○")
        mark.set_markup('<span foreground="%s">%s</span>' % (colour, glyph))
        mark.set_valign(Gtk.Align.START)
        row.pack_start(mark, False, False, 0)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title = Gtk.Label(xalign=0.0)
        title.set_markup(GLib.markup_escape_text(name))
        title.set_line_wrap(True)
        col.pack_start(title, False, False, 0)
        if detail:
            sub = Gtk.Label(xalign=0.0)
            sub.set_markup('<span size="small" foreground="%s">%s</span>'
                           % (colour if ok is False else MEH,
                              GLib.markup_escape_text(detail)))
            sub.set_line_wrap(True)
            sub.set_ellipsize(Pango.EllipsizeMode.END)
            col.pack_start(sub, False, False, 0)
        if blurb:
            note = Gtk.Label(xalign=0.0)
            note.set_markup('<span size="small" foreground="%s">%s</span>'
                            % (MEH, GLib.markup_escape_text(blurb)))
            note.set_line_wrap(True)
            col.pack_start(note, False, False, 0)
        row.pack_start(col, True, True, 0)
        self.rows.pack_start(row, False, False, 0)
