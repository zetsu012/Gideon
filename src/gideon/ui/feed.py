"""Client half of the daemon's status socket, with reconnection.

The UI's whole job is to be trustworthy about whether Gideon is alive, so the
interesting part of this module is not the happy path - it is what happens when
the daemon is not there. Rules:

  * **Absence is a state, not an error.** The daemon can be stopped, restarting
    after a crash, or not installed yet. Each of those simply produces
    `on_offline(reason)` and a retry; nothing raises and nothing gives up.
  * **Reconnect forever, but politely.** The backoff grows to a few seconds so a
    permanently absent daemon costs nothing, and resets the instant a connection
    succeeds - a systemd `Restart=on-failure` bounce should repaint the icon
    within a second, not after a minute of exponential backoff.
  * **Silence is not health.** The daemon sends a heartbeat while idle, so a
    connection that has gone quiet past the deadline is treated as dead even
    though the unix socket itself never noticed.

Stdlib only, and no GTK: this runs on its own thread and hands dictionaries to
the GTK side, which is responsible for bouncing them onto the main loop.
"""
from __future__ import annotations
import json, os, socket, threading, time
from pathlib import Path

# Mirrors gideon.core.state - re-stated, not imported (see the package docstring).
STARTING, IDLE, LISTENING = "starting", "idle", "listening"
THINKING, SPEAKING, FOLLOWUP = "thinking", "speaking", "followup"
STOPPED, OFFLINE = "stopped", "offline"
ACTIVE = (LISTENING, THINKING, SPEAKING, FOLLOWUP)

RETRY_MIN_S, RETRY_MAX_S = 0.5, 5.0
#: The daemon heartbeats every 5 s; miss two and call it gone.
DEAD_AFTER_S = 12.0


def socket_path() -> Path:
    """Must match gideon.ipc.control.default_path()."""
    if "GIDEON_SOCKET" in os.environ:
        return Path(os.environ["GIDEON_SOCKET"])
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/gideon-{os.getuid()}"
    return Path(runtime) / "gideon.sock"


def send(command: str, path: Path | None = None, timeout: float = 1.0) -> bool:
    """One-shot command (`wake`, `ping`). False if nothing is listening."""
    target = path or socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(target))
            sock.sendall(command.encode() + b"\n")
            return sock.recv(16).strip() == b"ok"
    except OSError:
        return False


class StatusFeed:
    """Subscribes to the daemon and calls back on every change.

    Callbacks arrive on this object's own thread. `on_status(dict)` carries a
    full snapshot; `on_offline(reason)` means there is no daemon to talk to.
    """

    def __init__(self, on_status, on_offline, path: Path | None = None):
        self.path = path or socket_path()
        self.on_status = on_status
        self.on_offline = on_offline
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        delay = RETRY_MIN_S
        announced = False
        while not self._stop.is_set():
            try:
                self._session()
                delay, announced = RETRY_MIN_S, False   # clean disconnect: retry at once
            except OSError as exc:
                # Announce the outage once per outage, not once per retry: the
                # icon should go grey immediately and then stay quiet.
                if not announced:
                    self.on_offline(self._explain(exc))
                    announced = True
                self._stop.wait(delay)
                delay = min(RETRY_MAX_S, delay * 2)

    def _explain(self, exc: OSError) -> str:
        if isinstance(exc, (FileNotFoundError, ConnectionRefusedError)):
            return ("the daemon is not running" if not self.path.exists()
                    else "the daemon left a stale socket behind")
        return f"{type(exc).__name__}: {exc}"

    def _session(self) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(str(self.path))
            sock.sendall(b"subscribe\n")
            sock.settimeout(DEAD_AFTER_S)
            with sock.makefile("rb") as lines:
                for raw in lines:
                    if self._stop.is_set():
                        return
                    if not raw.strip():
                        continue
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue          # a truncated line is not fatal
                    if msg.get("type") == "status":
                        msg["received_at"] = time.time()
                        self.on_status(msg)
        # The daemon closed the connection: it is shutting down.
        raise ConnectionResetError("the daemon closed the connection")
