"""The daemon's edge to the rest of the desktop: one unix socket, two jobs.

**Arming.** A push-to-talk key cannot announce itself through the microphone,
and it must not start a second Gideon: the daemon already owns the mic, and two
pipelines cannot share it. So a `wake` line is treated exactly as if the wake
phrase had just been heard - the utterance that follows is routed to the brain.

**Telling.** A daemon with no window is indistinguishable from a dead one. The
same socket therefore answers `status` with a snapshot of `core.state.StatusBus`
and, for `subscribe`, streams a fresh JSON line on every change - which is what
the tray icon and the HUD in `gideon/ui/` render. Push rather than poll: a state
change has to reach the screen while the user is still speaking, and a UI that
woke up four times a second to ask "anything yet?" would be a battery drain for
a daemon that is idle almost all the time.

Two rules hold this together:

  * **A client can never stall the pipeline.** Each connection is served by its
    own thread, and a subscriber's updates go through a small bounded queue.
    A UI that stops reading loses updates and is eventually dropped; the main
    loop never notices.
  * **The protocol is trivial** - newline commands in, newline JSON out, no
    framing and no auth beyond the 0600 file mode - because it is local,
    per-user, and worth no more complexity than that.
"""
from __future__ import annotations
import json, logging, os, queue, socket, threading, time
from pathlib import Path

log = logging.getLogger("gideon.control")

#: Dropped updates are invisible in a UI that only ever renders the newest
#: snapshot, so the queue is short on purpose: the goal is "never block", not
#: "never lose an intermediate frame".
FEED_QUEUE = 16
#: Sent when nothing has changed, so a UI can tell "daemon quiet" from
#: "daemon gone" without waiting for the TCP-less socket to notice a dead peer.
HEARTBEAT_S = 5.0


def default_path() -> Path:
    """Where the daemon listens. $XDG_RUNTIME_DIR is per-user and tmpfs-backed,
    so a stale socket cannot survive a reboot; /tmp is the fallback for sessions
    without one (a bare ssh login, for instance)."""
    if "GIDEON_SOCKET" in os.environ:
        return Path(os.environ["GIDEON_SOCKET"])
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/gideon-{os.getuid()}"
    return Path(runtime) / "gideon.sock"


class Control:
    """Serves the control socket: arms push-to-talk, publishes daemon status."""

    def __init__(self, path: Path | None = None, window_s: float = 10.0, bus=None):
        self.path = Path(path) if path else default_path()
        self.window_s = window_s
        self.bus = bus                 # core.state.StatusBus, or None
        self._until = 0.0
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._feeds: set[queue.Queue] = set()
        self._feeds_lock = threading.Lock()

    # -- daemon side -------------------------------------------------------
    def start(self) -> bool:
        """Bind and serve in a background thread. Never fatal: a daemon that
        cannot bind still works, it just cannot be pushed-to-talk and shows no
        tray icon."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # A leftover file from a killed daemon would make bind() fail with
            # EADDRINUSE even though nobody is listening - but a *live* daemon
            # leaves an identical-looking file. Unlinking blindly would take the
            # socket away from the running instance: the key would arm a daemon
            # that does not own the microphone, and the tray would faithfully
            # report the state of the wrong process. So ask first.
            if self.path.exists():
                if send("ping", self.path, timeout=0.5):
                    raise OSError(f"another Gideon is already serving {self.path}")
                self.path.unlink()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(self.path))
            os.chmod(self.path, 0o600)
            sock.listen(8)
            sock.settimeout(0.5)          # so stop() is noticed promptly
        except OSError as exc:
            log.warning("control socket unavailable (%s): push-to-talk and the "
                        "tray indicator are disabled", exc)
            if self.bus is not None:
                self.bus.health_set("control", False, str(exc))
            return False
        self._sock = sock
        self._thread = threading.Thread(target=self._accept, name="control", daemon=True)
        self._thread.start()
        if self.bus is not None:
            self.bus.subscribe(self._publish)
            self.bus.health_set("control", True, str(self.path))
        log.info("control socket: %s", self.path)
        return True

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve_one, args=(conn,),
                             name="control-conn", daemon=True).start()

    def _serve_one(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(2.0)
            try:
                cmd = conn.recv(64).decode("utf-8", "replace").strip().lower()
            except OSError:
                return
            if cmd == "wake":
                self.arm()
                self._send(conn, b"ok\n")
            elif cmd == "ping":
                self._send(conn, b"ok\n")
            elif cmd == "status":
                self._send(conn, self._snapshot_line())
            elif cmd == "subscribe":
                self._feed(conn)
            else:
                log.debug("unknown control command %r", cmd)
                self._send(conn, b"err\n")

    @staticmethod
    def _send(conn: socket.socket, payload: bytes) -> None:
        try:
            conn.sendall(payload)
        except OSError:
            pass

    def _snapshot_line(self) -> bytes:
        snap = self.bus.snapshot() if self.bus is not None else {
            "type": "status", "state": "unknown",
            "detail": "this daemon publishes no status"}
        return json.dumps(snap, separators=(",", ":")).encode() + b"\n"

    # -- the status feed ---------------------------------------------------
    def _publish(self, snapshot: dict) -> None:
        """StatusBus callback. Runs on the pipeline's thread, so it does exactly
        one non-blocking put per subscriber and returns."""
        line = json.dumps(snapshot, separators=(",", ":")).encode() + b"\n"
        with self._feeds_lock:
            feeds = list(self._feeds)
        for q in feeds:
            try:
                q.put_nowait(line)
            except queue.Full:
                # Drop the oldest: a UI wants the newest state, not a backlog.
                try:
                    q.get_nowait()
                    q.put_nowait(line)
                except (queue.Empty, queue.Full):
                    pass

    def _feed(self, conn: socket.socket) -> None:
        """Stream snapshots to one subscriber until it goes away."""
        q: queue.Queue = queue.Queue(maxsize=FEED_QUEUE)
        with self._feeds_lock:
            self._feeds.add(q)
        # The first line is the current state, so a UI that connects mid-session
        # is correct immediately instead of blank until something happens.
        try:
            conn.settimeout(HEARTBEAT_S + 5.0)
            conn.sendall(self._snapshot_line())
            while not self._stop.is_set():
                try:
                    line = q.get(timeout=HEARTBEAT_S)
                except queue.Empty:
                    line = b'{"type":"heartbeat"}\n'
                conn.sendall(line)
        except OSError:
            pass                      # client closed, or is not reading: done
        finally:
            with self._feeds_lock:
                self._feeds.discard(q)

    # -- arming ------------------------------------------------------------
    def arm(self) -> None:
        with self._lock:
            self._until = time.time() + self.window_s
        if self.bus is not None:
            self.bus.windows(armed_until=self._until)
        log.info("KEY  push-to-talk armed for %.0fs", self.window_s)

    def consume(self) -> bool:
        """True once per press: the next utterance is a query."""
        with self._lock:
            armed = time.time() < self._until
            self._until = 0.0
        if armed and self.bus is not None:
            self.bus.windows(armed_until=0.0)
        return armed

    def close(self) -> None:
        self._stop.set()
        if self.bus is not None:
            self.bus.unsubscribe(self._publish)
        if self._sock is not None:
            self._sock.close()
        try:
            self.path.unlink()
        except OSError:
            pass


def send(command: str = "wake", path: Path | None = None, timeout: float = 1.0) -> bool:
    """Client side. Returns False if no daemon is listening."""
    target = Path(path) if path else default_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(target))
            sock.sendall(command.encode() + b"\n")
            return sock.recv(16).strip() == b"ok"
    except OSError:
        return False


def status(path: Path | None = None, timeout: float = 1.0) -> dict | None:
    """One-shot snapshot, or None if no daemon is listening."""
    target = Path(path) if path else default_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(target))
            sock.sendall(b"status\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode()) if buf.strip() else None
    except (OSError, ValueError):
        return None
