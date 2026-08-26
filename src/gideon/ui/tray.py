#!/usr/bin/env python3
"""Gideon's tray indicator: the proof that the daemon is at your service.

    python3 src/gideon/ui/tray.py          # or: gideon --ui

What it does, in order of importance:

  1. **Exists only when Gideon does.** The icon reflects a live subscription to
     the daemon's control socket. Daemon gone, killed or crash-looping - the
     icon goes red and struck through within a second or two, on its own. It is
     never a static "installed" badge.
  2. **Shows the state.** Ready / listening / thinking / speaking / follow-up,
     as the colour and the tooltip, backed by `hud.py` on screen.
  3. **Answers "is everything working".** The menu opens a health panel with one
     row per subsystem, each row a measurement rather than an assumption.
  4. **Lets you act.** Arm push-to-talk, and start/restart/stop the daemon.

Backend note: on GNOME Wayland a client cannot place a window or keep it above
others, because Mutter implements no layer-shell protocol. The HUD needs both,
so this process re-execs itself onto XWayland when one is available. The tray
icon itself is D-Bus (StatusNotifierItem) and does not care either way.
"""
from __future__ import annotations
import argparse, os, shutil, socket, subprocess, sys, time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk                       # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feed, theme                                        # noqa: E402
from hud import Hud                                       # noqa: E402
from panel import HealthPanel                             # noqa: E402

APP_ID = "gideon-indicator"
#: Abstract unix socket, so the lock disappears with the process even on SIGKILL
#: and can never be left behind as a stale file the way a pidfile can.
SINGLETON_ADDR = "\0gideon-indicator-%d" % os.getuid()


def load_indicator():
    """AppIndicator, under whichever name this distro ships it. None if absent."""
    for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(namespace, "0.1")
            return __import__("gi.repository", fromlist=[namespace]).__dict__[namespace]
        except (ValueError, ImportError, KeyError):
            continue
    return None


def claim_singleton() -> socket.socket | None:
    """Bind the abstract address; None if another indicator already holds it."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(SINGLETON_ADDR)
    except OSError:
        sock.close()
        return None
    return sock


def want_x11() -> bool:
    """True if we should switch to XWayland for a placeable, always-on-top HUD."""
    return (os.environ.get("XDG_SESSION_TYPE") == "wayland"
            and not os.environ.get("GDK_BACKEND")
            and bool(os.environ.get("DISPLAY")))


def reexec_on_x11() -> None:
    os.environ["GDK_BACKEND"] = "x11"
    os.environ["GIDEON_UI_BACKEND_SWITCHED"] = "1"
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), *sys.argv[1:]])


def systemctl(*args: str) -> bool:
    if not shutil.which("systemctl"):
        return False
    return subprocess.call(["systemctl", "--user", *args],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


class Tray:
    def __init__(self, show_hud: bool = True):
        self.snapshot: dict = {}
        self.state = feed.OFFLINE
        self.hud = Hud() if show_hud else None
        self.panel = HealthPanel(lambda: self.snapshot)

        icon_dir = theme.render_icons()
        self.indicator = None
        api = load_indicator()
        if api is not None:
            self.indicator = api.Indicator.new_with_path(
                APP_ID, theme.icon_name(feed.OFFLINE),
                api.IndicatorCategory.APPLICATION_STATUS, str(icon_dir))
            self.indicator.set_status(api.IndicatorStatus.ACTIVE)
            self.indicator.set_title("Gideon")
            self.indicator.set_menu(self._build_menu())
        else:
            print("no AppIndicator typelib found; the tray icon is disabled.\n"
                  "  sudo apt install gir1.2-ayatanaappindicator3-0.1\n"
                  "The HUD and the health panel still work.", file=sys.stderr)
            self.panel.show_all()

        self.feed = feed.StatusFeed(self._on_status, self._on_offline)
        self.feed.start()
        # Nothing has arrived yet; paint the honest state rather than a blank
        # icon that would imply everything is fine.
        self._render()

    # -- menu --------------------------------------------------------------
    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        self.state_item = Gtk.MenuItem(label="Connecting…")
        self.state_item.set_sensitive(False)
        menu.append(self.state_item)
        self.heard_item = Gtk.MenuItem(label="")
        self.heard_item.set_sensitive(False)
        self.heard_item.hide()
        menu.append(self.heard_item)
        menu.append(Gtk.SeparatorMenuItem())

        health = Gtk.MenuItem(label="Service health…")
        health.connect("activate", self._open_panel)
        menu.append(health)

        self.talk_item = Gtk.MenuItem(label="Talk to Gideon")
        self.talk_item.connect("activate", self._arm)
        menu.append(self.talk_item)
        menu.append(Gtk.SeparatorMenuItem())

        self.power_item = Gtk.MenuItem(label="Start daemon")
        self.power_item.connect("activate", self._power)
        menu.append(self.power_item)
        restart = Gtk.MenuItem(label="Restart daemon")
        restart.connect("activate", lambda *_: self._systemctl_feedback("restart"))
        menu.append(restart)
        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit indicator")
        quit_item.connect("activate", self._quit)
        menu.append(quit_item)
        menu.show_all()
        self.heard_item.hide()
        return menu

    def _open_panel(self, *_):
        self.panel.show_all()
        self.panel.present()

    def _arm(self, *_):
        """Same signal the push-to-talk key sends: the next thing said is a query."""
        if feed.send("wake"):
            if self.hud is not None:
                self.hud.flash("Go ahead — no wake phrase needed",
                               state=feed.LISTENING, seconds=3.0)
        elif self.hud is not None:
            self.hud.flash("Gideon is not running", state=feed.OFFLINE, seconds=3.0)

    def _power(self, *_):
        self._systemctl_feedback("stop" if self._online() else "start")

    def _systemctl_feedback(self, verb: str) -> None:
        done = systemctl(verb, "gideon.service")
        if self.hud is not None:
            self.hud.flash("%s the daemon: %s" % (verb.capitalize(), "ok" if done else "failed"),
                           state=feed.IDLE if done else feed.OFFLINE, seconds=2.5)

    def _quit(self, *_):
        self.feed.stop()
        Gtk.main_quit()

    # -- feed --------------------------------------------------------------
    def _online(self) -> bool:
        return self.state not in (feed.OFFLINE, feed.STOPPED)

    def _on_status(self, snap: dict) -> None:
        GLib.idle_add(self._absorb, snap)

    def _on_offline(self, reason: str) -> None:
        GLib.idle_add(self._absorb, {"type": "status", "state": feed.OFFLINE,
                                     "detail": reason})

    def _absorb(self, snap: dict) -> bool:
        self.snapshot = snap
        self.state = snap.get("state", feed.OFFLINE)
        self._render()
        return False                      # one-shot idle callback

    def _render(self) -> None:
        if self.indicator is not None:
            self.indicator.set_icon_full(theme.icon_name(self.state), theme.label(self.state))
            self.state_item.set_label("Gideon — %s" % theme.label(self.state).lower())
            heard = self.snapshot.get("transcript")
            if heard:
                self.heard_item.set_label("heard: “%s”" % heard[:60])
                self.heard_item.show()
            else:
                self.heard_item.hide()
            self.talk_item.set_sensitive(self._online())
            self.power_item.set_label("Stop daemon" if self._online() else "Start daemon")
        if self.hud is not None:
            self.hud.apply(self.snapshot or {"state": self.state})
        if self.panel.get_visible():
            self.panel.refresh()


# --------------------------------------------------------------------------- #
# Self-check
# --------------------------------------------------------------------------- #
# The daemon's invariants are asserted by `gideon --selftest`, but it runs on the
# vendored interpreter and cannot import GTK, so the UI needs its own. What is
# worth asserting here is not that widgets construct - it is the one rule with
# real consequences: *which turns reach the screen*. Getting it wrong in either
# direction is a bug the user notices immediately - a HUD that stays dark when
# they press the key, or one that puts every passing conversation on the desktop.
SELF_CHECK = [
    # (label, expected visibility, snapshot overrides)
    ("key pressed, still idle",       True,  dict(state=feed.IDLE, armed=True)),
    ("speaking after the key",        True,  dict(state=feed.LISTENING, armed=True)),
    ("transcribing after the key",    True,  dict(state=feed.THINKING, armed=True)),
    ("answered a keyed query",        True,  dict(state=feed.SPEAKING, transcript="what time is it",
                                                  transcript_kind="key", transcript_at=2.0,
                                                  reply="Just past three.")),
    ("follow-up window open",         True,  dict(state=feed.FOLLOWUP, follow_for=8.0,
                                                  transcript="what time is it",
                                                  transcript_kind="key", transcript_at=2.0)),
    ("someone else starts talking",   False, dict(state=feed.LISTENING)),
    ("...being transcribed",          False, dict(state=feed.THINKING)),
    ("...and it was not for Gideon",  False, dict(state=feed.IDLE, transcript="anyway i told him",
                                                  transcript_kind="ignored", transcript_at=3.0)),
    ("wake phrase, not yet ruled on", False, dict(state=feed.LISTENING)),
    ("wake phrase matched",           True,  dict(state=feed.THINKING, transcript="hey gideon hello",
                                                  transcript_kind="wake", transcript_at=4.0)),
    ("daemon gone",                   True,  dict(state=feed.OFFLINE)),
]


def self_check() -> int:
    """Drive the HUD through a scripted conversation and check what it shows."""
    hud = Hud()
    base = dict(type="status", state=feed.IDLE, transcript="", transcript_kind="",
                reply="", armed=False, follow_for=0.0, transcript_at=0.0)
    failures = 0
    for label, expected, over in SELF_CHECK:
        snap = dict(base)
        snap.update(over)
        hud.apply(snap)
        # Withdrawal is deferred to a 250 ms timer, so the loop has to actually
        # run before asking what is on screen. Checking straight after apply()
        # would report every hide as a failure - the HUD is on its way out, not
        # staying up.
        deadline = time.time() + 0.4
        while time.time() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.02)
        got = hud.get_visible()
        if got != expected:
            failures += 1
        print("  %-4s %-34s hud %s (wanted %s)"
              % ("ok" if got == expected else "FAIL", label,
                 "shown" if got else "hidden", "shown" if expected else "hidden"))
    print("selftest %s" % ("OK" if not failures else "FAILED (%d)" % failures))
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gideon-ui", description="Gideon tray indicator")
    ap.add_argument("--no-hud", action="store_true",
                    help="tray icon and health panel only, no on-screen overlay")
    ap.add_argument("--no-x11", action="store_true",
                    help="stay on the native backend; the HUD may be misplaced on Wayland")
    ap.add_argument("--health", action="store_true",
                    help="print one health snapshot as text and exit")
    ap.add_argument("--self-check", action="store_true", dest="self_check",
                    help="assert which turns the HUD shows, then exit")
    args = ap.parse_args(argv)

    if args.health:
        snap = {}
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(2.0)
                s.connect(str(feed.socket_path()))
                s.sendall(b"status\n")
                import json
                snap = json.loads(s.makefile("rb").readline() or b"{}")
        except (OSError, ValueError):
            pass
        if not snap:
            print("Gideon: offline (nothing listening on %s)" % feed.socket_path())
            return 1
        print("Gideon: %s (up %.0fs, pid %s)" % (theme.label(snap["state"]),
                                                 snap["uptime"], snap["pid"]))
        for key, entry in snap.get("health", {}).items():
            name = theme.SUBSYSTEMS.get(key, (key, ""))[0]
            print("  %s %-16s %s" % ("OK " if entry["ok"] else "BAD", name, entry["detail"]))
        return 0

    if not args.no_hud and not args.no_x11 and want_x11():
        reexec_on_x11()                                   # does not return

    if args.self_check:
        return self_check()

    lock = claim_singleton()
    if lock is None:
        print("another Gideon indicator is already running", file=sys.stderr)
        return 0

    Tray(show_hud=not args.no_hud)
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
