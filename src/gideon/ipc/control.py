"""Out-of-band 'the next thing I say is a query' signal for a running daemon.

A push-to-talk key cannot announce itself through the microphone, and it must
not start a second Gideon: the daemon already owns the mic, and two pipelines
cannot share it. So the daemon listens on a unix socket and treats a `wake`
line exactly as if the wake phrase had just been heard - the utterance that
follows is routed to the brain instead of being ignored.

The socket is deliberately trivial (newline commands, no framing, no auth
beyond the 0600 file mode) because it is local, per-user, and carries one bit.
"""
from __future__ import annotations
import logging, os, socket, threading, time
from pathlib import Path

log = logging.getLogger("gideon.control")


def default_path() -> Path:
    """Where the daemon listens. $XDG_RUNTIME_DIR is per-user and tmpfs-backed,
    so a stale socket cannot survive a reboot; /tmp is the fallback for sessions
    without one (a bare ssh login, for instance)."""
    if "GIDEON_SOCKET" in os.environ:
        return Path(os.environ["GIDEON_SOCKET"])
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/gideon-{os.getuid()}"
    return Path(runtime) / "gideon.sock"


class Control:
    """Accepts `wake` on a unix socket and holds it as a short-lived arm.

    The arm expires: pressing the key and then walking away must not turn the
    next unrelated sentence in the room into a query an hour later.
    """

    def __init__(self, path: Path | None = None, window_s: float = 10.0):
        self.path = Path(path) if path else default_path()
        self.window_s = window_s
        self._until = 0.0
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- daemon side -------------------------------------------------------
    def start(self) -> bool:
        """Bind and serve in a background thread. Never fatal: a daemon that
        cannot bind still works, it just cannot be pushed-to-talk."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # A leftover file from a killed daemon would make bind() fail with
            # EADDRINUSE even though nobody is listening.
            if self.path.exists():
                self.path.unlink()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(self.path))
            os.chmod(self.path, 0o600)
            sock.listen(4)
            sock.settimeout(0.5)          # so stop() is noticed promptly
        except OSError as exc:
            log.warning("control socket unavailable (%s): push-to-talk disabled", exc)
            return False
        self._sock = sock
        self._thread = threading.Thread(target=self._serve, name="control", daemon=True)
        self._thread.start()
        log.info("control socket: %s", self.path)
        return True

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(1.0)
                try:
                    cmd = conn.recv(64).decode("utf-8", "replace").strip().lower()
                except OSError:
                    continue
                if cmd == "wake":
                    with self._lock:
                        self._until = time.time() + self.window_s
                    log.info("KEY  push-to-talk armed for %.0fs", self.window_s)
                    reply = b"ok\n"
                elif cmd == "ping":
                    reply = b"ok\n"
                else:
                    log.debug("unknown control command %r", cmd)
                    reply = b"err\n"
                try:
                    conn.sendall(reply)
                except OSError:
                    pass

    def consume(self) -> bool:
        """True once per press: the next utterance is a query."""
        with self._lock:
            armed = time.time() < self._until
            self._until = 0.0
        return armed

    def close(self) -> None:
        self._stop.set()
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
