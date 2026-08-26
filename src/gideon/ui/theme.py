"""One place for the colours, the words and the icons the UI paints.

Kept apart from the widgets so that "what does listening look like" is a data
question with one answer, shared by the tray icon, the HUD orb and the health
panel. Changing the palette here changes all three at once and cannot leave them
disagreeing about which state is which colour - which would be the one bug this
UI must never have, since its entire purpose is to be believed.
"""
from __future__ import annotations
import math, os, sys
from pathlib import Path

# Executed as a script, never imported as a package (see __init__.py), so the
# sibling modules are reached the way gideon/hotkey/ reaches its own.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import feed                                                          # noqa: E402

#: state -> (accent rgb 0-1, short label, one-line explanation for the tooltip)
STATES: dict[str, tuple[tuple[float, float, float], str, str]] = {
    feed.STARTING:  ((0.60, 0.60, 0.65), "Starting",   "loading the speech models"),
    feed.IDLE:      ((0.30, 0.78, 0.47), "Ready",      'listening for "hey Gideon"'),
    feed.LISTENING: ((0.26, 0.62, 0.98), "Listening",  "hearing you speak"),
    feed.THINKING:  ((0.98, 0.75, 0.20), "Thinking",   "transcribing and answering"),
    feed.SPEAKING:  ((0.71, 0.47, 0.98), "Speaking",   "replying; the microphone is muted"),
    feed.FOLLOWUP:  ((0.20, 0.80, 0.80), "Follow-up",  "still open - no wake phrase needed"),
    feed.STOPPED:   ((0.55, 0.55, 0.60), "Stopped",    "the daemon shut down"),
    feed.OFFLINE:   ((0.88, 0.34, 0.34), "Offline",    "no daemon is listening"),
}

#: Friendly names for the health keys the daemon publishes.
SUBSYSTEMS = {
    "mic":     ("Microphone", "the capture stream the daemon holds open"),
    "vad":     ("Voice activity", "Silero VAD - decides where an utterance starts and ends"),
    "stt":     ("Speech to text", "faster-whisper - transcribes every segment"),
    "tts":     ("Speech out", "Piper - synthesises the spoken reply"),
    "llm":     ("Local brain", "Ollama - optional; canned replies without it"),
    "control": ("Control socket", "push-to-talk and this indicator"),
}


def accent(state: str) -> tuple[float, float, float]:
    return STATES.get(state, STATES[feed.OFFLINE])[0]


def label(state: str) -> str:
    return STATES.get(state, STATES[feed.OFFLINE])[1]


def describe(state: str) -> str:
    return STATES.get(state, STATES[feed.OFFLINE])[2]


def hex_of(state: str) -> str:
    r, g, b = accent(state)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


# --------------------------------------------------------------------------- #
# Tray icons
# --------------------------------------------------------------------------- #
# Drawn at startup rather than shipped as files: the set is one small glyph per
# state, they must all agree with the palette above, and a themed icon directory
# is the only thing AppIndicator will reliably load on GNOME.
ICON_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "gideon-ui" / "icons"
ICON_SIZE = 22


def _mic(cr, size: float) -> None:
    """A microphone outline: capsule, stand, base."""
    cx, s = size / 2, size / 22.0
    cr.set_line_width(2.0 * s)
    cr.set_line_cap(1)                                  # round
    # capsule
    r = 3.1 * s
    cr.new_path()
    cr.arc(cx, 7.5 * s, r, math.pi, 2 * math.pi)
    cr.arc(cx, 11.0 * s, r, 0, math.pi)
    cr.close_path()
    cr.fill()
    # cradle
    cr.new_path()
    cr.arc(cx, 11.0 * s, 5.6 * s, 0.15 * math.pi, 0.85 * math.pi)
    cr.stroke()
    # stand
    cr.move_to(cx, 16.6 * s); cr.line_to(cx, 19.0 * s); cr.stroke()


def render_icons() -> Path:
    """Draw one PNG per state into a private themed directory; return it."""
    import cairo
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for state in STATES:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, ICON_SIZE, ICON_SIZE)
        cr = cairo.Context(surface)
        r, g, b = accent(state)
        if state in (feed.OFFLINE, feed.STOPPED):
            # Offline is drawn hollow and struck through, not merely a different
            # colour: the indicator has to survive a monochrome/symbolic panel
            # theme where every state would otherwise look identical.
            cr.set_source_rgba(r, g, b, 0.85)
            _mic(cr, ICON_SIZE)
            cr.set_line_width(2.0)
            cr.move_to(4, 18); cr.line_to(18, 4); cr.stroke()
        else:
            cr.set_source_rgb(r, g, b)
            _mic(cr, ICON_SIZE)
            if state in (feed.LISTENING, feed.SPEAKING, feed.THINKING):
                cr.arc(ICON_SIZE - 5, 5, 3.2, 0, 2 * math.pi)   # activity pip
                cr.fill()
        surface.write_to_png(str(ICON_DIR / f"gideon-{state}.png"))
    return ICON_DIR


def icon_name(state: str) -> str:
    return f"gideon-{state if state in STATES else feed.OFFLINE}"
