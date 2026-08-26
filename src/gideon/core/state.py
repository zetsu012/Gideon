"""Observable daemon state: what Gideon is doing, and whether each part works.

The daemon is a single-threaded pipeline and must stay that way - nothing here
may block it. So this is a write-cheap, read-anywhere bulletin board: the main
loop stamps a transition with one method call under a short lock, and anyone
watching (today: the unix-socket UI feed in `ipc/control.py`) is handed a
snapshot through a *non-blocking* callback. A subscriber that cannot keep up
loses updates; it never slows the microphone down.

Two kinds of fact live here:

  * **state** - where the pipeline is right now (idle / listening / thinking /
    speaking / follow-up). This is what the tray icon and the HUD render, and it
    is the honest answer to "is Gideon actually at my service".
  * **health** - one entry per subsystem (mic, vad, stt, tts, llm, control
    socket), set once at startup and updated when something fails at runtime.
    The tray's health panel is a view of this dict and nothing else, so it can
    never claim a component is fine because a hardcoded list said so.

Both are pure data. Nothing in this module imports audio, models or GTK.
"""
from __future__ import annotations
import logging, os, threading, time

log = logging.getLogger("gideon.state")
_PID = os.getpid()

# Pipeline states. Strings, not an enum: they cross a socket as JSON and are
# matched by a UI running on a different Python interpreter entirely.
STARTING  = "starting"    # loading models; not listening yet
IDLE      = "idle"        # armed, waiting for the wake phrase or the key
LISTENING = "listening"   # VAD has an open segment - someone is talking
THINKING  = "thinking"    # transcribing / routing / asking the LLM
SPEAKING  = "speaking"    # Piper is playing, mic is muted
FOLLOWUP  = "followup"    # reply finished, still open for a follow-up
STOPPED   = "stopped"

#: States in which the HUD should be on screen.
ACTIVE = (LISTENING, THINKING, SPEAKING, FOLLOWUP)


class StatusBus:
    """Current state + per-subsystem health, with fan-out to watchers."""

    def __init__(self, version: str = "0.1"):
        self.version = version
        self._lock = threading.RLock()
        self._subs: list = []
        self._seq = 0
        self._stop = threading.Event()
        self._ticker: threading.Thread | None = None

        self.started_at = time.time()
        self.state = STARTING
        self.state_since = self.started_at
        self.transcript = ""          # last thing Whisper heard
        self.transcript_kind = ""     # wake | follow | key | ignored
        self.transcript_at = 0.0
        self.reply = ""               # last thing Gideon said
        self.partial = ""             # reserved: streaming transcript, if ever
        self.armed_until = 0.0        # push-to-talk window
        self.follow_until = 0.0       # follow-up window
        self.health: dict[str, dict] = {}
        self.counters = {"utterances": 0, "wakes": 0, "replies": 0, "errors": 0}
        self.last_error = ""

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        """Run the expiry ticker.

        The follow-up and push-to-talk windows end by the clock running out, not
        by anything the pipeline does - and the pipeline is blocked on the
        microphone at that moment, so it cannot announce the change itself. A
        UI that showed "listening for a follow-up" forever would be lying, so
        one small thread watches the two deadlines and publishes their expiry.
        """
        if self._ticker is not None:
            return
        self._ticker = threading.Thread(target=self._tick, name="status", daemon=True)
        self._ticker.start()

    def _tick(self) -> None:
        while not self._stop.wait(0.25):
            with self._lock:
                now = time.time()
                expired = (self.state == FOLLOWUP and now >= self.follow_until)
                armed_expired = 0 < self.armed_until <= now
                if armed_expired:
                    self.armed_until = 0.0
                if not (expired or armed_expired):
                    continue
                if expired:
                    self._set_state_locked(IDLE)
                else:
                    self._emit_locked()

    def close(self) -> None:
        self._stop.set()
        self.set_state(STOPPED)

    # -- writers (called from the pipeline; all cheap) ----------------------
    def set_state(self, state: str) -> None:
        with self._lock:
            self._set_state_locked(state)

    def _set_state_locked(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        self.state_since = time.time()
        self._emit_locked()

    def heard(self, text: str, kind: str) -> None:
        """Whisper produced `text`; `kind` says why it did or didn't count."""
        with self._lock:
            self.transcript = text
            self.transcript_kind = kind
            self.transcript_at = time.time()
            self.counters["utterances"] += 1
            if kind in ("wake", "key", "follow"):
                self.counters["wakes"] += 1
            self._emit_locked()

    def spoke(self, reply: str) -> None:
        with self._lock:
            self.reply = reply
            self.counters["replies"] += 1
            self._emit_locked()

    def windows(self, *, follow_until: float | None = None,
                armed_until: float | None = None) -> None:
        with self._lock:
            if follow_until is not None:
                self.follow_until = follow_until
            if armed_until is not None:
                self.armed_until = armed_until
            self._emit_locked()

    def health_set(self, name: str, ok: bool, detail: str = "") -> None:
        """Record a subsystem's condition. Called at load time and on failure."""
        with self._lock:
            prev = self.health.get(name)
            entry = {"ok": bool(ok), "detail": detail, "at": time.time()}
            self.health[name] = entry
            if not ok and (prev is None or prev["ok"]):
                log.warning("health: %s degraded (%s)", name, detail or "no detail")
            self._emit_locked()

    def error(self, message: str) -> None:
        with self._lock:
            self.last_error = message
            self.counters["errors"] += 1
            self._emit_locked()

    # -- readers -----------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            return {
                "type": "status",
                "seq": self._seq,
                "version": self.version,
                "now": now,
                "pid": _PID,
                "state": self.state,
                "state_since": self.state_since,
                "uptime": now - self.started_at,
                "transcript": self.transcript,
                "transcript_kind": self.transcript_kind,
                "transcript_at": self.transcript_at,
                "reply": self.reply,
                "armed": self.armed_until > now,
                "armed_for": max(0.0, self.armed_until - now),
                "follow_for": max(0.0, self.follow_until - now),
                "health": dict(self.health),
                "counters": dict(self.counters),
                "last_error": self.last_error,
            }

    # -- fan-out -----------------------------------------------------------
    def subscribe(self, callback) -> None:
        """`callback(snapshot_dict)` must not block and must not raise."""
        with self._lock:
            self._subs.append(callback)

    def unsubscribe(self, callback) -> None:
        with self._lock:
            if callback in self._subs:
                self._subs.remove(callback)

    def _emit_locked(self) -> None:
        self._seq += 1
        if not self._subs:
            return
        snap = self.snapshot()
        for cb in list(self._subs):
            try:
                cb(snap)
            except Exception:
                # A broken watcher is never allowed to break the pipeline.
                log.debug("status subscriber failed", exc_info=True)
