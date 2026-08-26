#!/usr/bin/env python3
"""Turn one key on one Bluetooth keyboard into a trigger for the voice agent.

    python3 hotkey/listener.py --device "Keychron" --keys KEY_MUTE

The device is grabbed exclusively, so the OS never sees that keyboard's events
and the button stops toggling system mute.  Every key that is NOT the trigger is
re-injected through /dev/uinput, so the keyboard keeps typing normally; if
uinput is unavailable the listener says so and keeps going in grab-only mode
(the whole keyboard goes quiet, which is fine for a dedicated remote and not
fine for the keyboard you type on).  Other input devices are untouched either
way - the grab is per-device.

Configuration comes from flags or the matching environment variables, so the
systemd unit can be edited without touching this file:

    GIDEON_HOTKEY_DEVICE   substring of the device name        (--device)
    GIDEON_HOTKEY_KEYS     comma-separated KEY_* names         (--keys)
    GIDEON_TRIGGER_CMD     command line to run on key-down     (--command)
"""
from __future__ import annotations
import argparse, errno, logging, os, selectors, shlex, signal, socket, subprocess, sys, time
from pathlib import Path

try:
    from evdev import InputDevice, UInput, ecodes
except ImportError:
    sys.exit("python3-evdev is not installed:  sudo apt install python3-evdev")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from device import key_name, permission_hint, resolve_by_name   # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_COMMAND = f"{REPO / 'run-local.sh'} --once"


def socket_path() -> Path:
    """Must match gideon.control.default_path(). Duplicated rather than
    imported: this listener runs on the system python, while gideon lives in a
    vendored runtime that is not importable from here."""
    if "GIDEON_SOCKET" in os.environ:
        return Path(os.environ["GIDEON_SOCKET"])
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/gideon-{os.getuid()}"
    return Path(runtime) / "gideon.sock"
RETRY_S = 2.0                    # poll interval while the keyboard is away
# Written by --learn, read at startup: which key on this keyboard is the trigger.
# It removes the need to ever look up a keycode by hand.
LEARNED = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gideon" / "hotkey-key"
FALLBACK_KEYS = "KEY_MUTE"

log = logging.getLogger("gideon.hotkey")


# --------------------------------------------------------------------------- #
# Step 4: the agent hook.  Everything above this line is input plumbing; swap
# the body of trigger_agent() to call the pipeline in-process instead of
# shelling out, and nothing else has to change.
# --------------------------------------------------------------------------- #
class AgentTrigger:
    """Tells Gideon that the next utterance is a query.

    Preferred path: the always-on daemon is already running and owns the
    microphone, so the press is a one-line message to its control socket - the
    daemon keeps listening exactly as before, it just routes what comes next to
    the brain without a wake phrase. Both can coexist; the wake phrase keeps
    working while the key is wired up.

    Fallback: no daemon is listening, so run a one-shot Gideon instead. That is
    the standalone mode - correct only because nothing else holds the mic.
    """

    def __init__(self, command: str, sock: Path | None = None):
        self.argv = shlex.split(command)
        self.sock = sock or socket_path()
        self.proc: subprocess.Popen | None = None

    def busy(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _signal_daemon(self) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect(str(self.sock))
                s.sendall(b"wake\n")
                return s.recv(16).strip() == b"ok"
        except OSError:
            return False        # no daemon, or a stale socket file

    def trigger_agent(self) -> None:
        if self._signal_daemon():
            log.info("armed the running daemon - speak now")
            return
        if self.busy():
            # A second press while the one-shot is still listening would fight
            # it for the microphone, so it is dropped rather than queued.
            log.info("trigger ignored: agent still running (pid %d)", self.proc.pid)
            return
        log.info("no daemon on %s; running one-shot: %s", self.sock, " ".join(self.argv))
        try:
            self.proc = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL)
        except OSError as exc:
            log.error("could not start agent: %s", exc)

    def shutdown(self) -> None:
        if self.busy():
            self.proc.terminate()


# --------------------------------------------------------------------------- #
# Input handling
# --------------------------------------------------------------------------- #
_stop = False


def _handle_signal(signum, _frame) -> None:
    global _stop
    _stop = True
    log.info("caught %s, shutting down", signal.Signals(signum).name)


def open_forwarder(dev: InputDevice) -> UInput | None:
    """A virtual keyboard that replays the events we are not consuming."""
    try:
        return UInput.from_device(dev, name=f"gideon-hotkey ({dev.name})")
    except Exception as exc:                 # evdev raises UInputError/OSError here
        log.warning("no /dev/uinput (%s) - running grab-only; every key on this "
                    "keyboard, not just the trigger, will stop reaching the desktop. "
                    "See hotkey/README.md for the udev rule that fixes this.", exc)
        return None


def pump(dev: InputDevice, codes: set[int], trigger: AgentTrigger, forward: bool) -> None:
    """Grab the device and dispatch its events until it disappears or we stop."""
    ui = open_forwarder(dev) if forward else None
    dev.grab()
    log.info("grabbed %r (%s); trigger keys: %s", dev.name, dev.path,
             ", ".join(sorted(key_name(c) for c in codes)))
    try:
        for event in dev.read_loop():
            if _stop:
                break
            if event.type == ecodes.EV_KEY and event.code in codes:
                if event.value == 1:             # key-down only; ignore up/autorepeat
                    trigger.trigger_agent()
                continue                         # never forwarded: this is our key now
            if ui is not None:
                ui.write_event(event)            # includes the EV_SYN that ends a report
    finally:
        try:
            dev.ungrab()
        except OSError:
            pass                                 # already gone with the device
        dev.close()
        if ui is not None:
            ui.close()


def learn_key(name: str, timeout_s: float = 60.0) -> int:
    """Watch the keyboard un-grabbed until a key goes down, and remember it.

    The device must not already be grabbed by anything - most obviously by a
    gideon-hotkey listener that an earlier setup left running. A grabbed device
    delivers its events to the grabber alone, so this loop would wait forever
    while the user pressed the key over and over. That is a silent hang with no
    diagnosis, so the grab is probed for up front and the timeout is a backstop.
    """
    path = resolve_by_name(name)
    if path is None:
        sys.exit(permission_hint() or
                 f"no input device matching {name!r} - is the keyboard connected?")
    dev = InputDevice(path)

    # grab()/ungrab() is the direct test: EBUSY means somebody else owns it.
    try:
        dev.grab()
        dev.ungrab()
    except OSError as exc:
        dev.close()
        if exc.errno == errno.EBUSY:
            sys.exit(f"{dev.name!r} is already grabbed by another process, so this "
                     f"would never see your key press.\n"
                     f"Almost always the key listener itself:\n"
                     f"    systemctl --user stop gideon-hotkey\n"
                     f"then try again (gideon --setup-key stops it for you).")
        sys.exit(f"cannot read {dev.name!r}: {exc}")

    print(f"Press the button you want to wake Gideon (on {dev.name!r}) ... ", flush=True)
    selector = selectors.DefaultSelector()
    selector.register(dev, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_s
    code = None
    try:
        while code is None:
            if not selector.select(max(0.0, deadline - time.monotonic())):
                sys.exit(f"\nno key press seen in {timeout_s:.0f}s. Is {dev.name!r} "
                         f"the keyboard you are pressing?")
            for event in dev.read():
                if event.type == ecodes.EV_KEY and event.value == 1:
                    code = event.code
                    break
    except KeyboardInterrupt:
        sys.exit("\naborted")
    except OSError:
        sys.exit("keyboard disconnected before a key was pressed")
    finally:
        selector.close()
        dev.close()
    key = key_name(code)
    LEARNED.parent.mkdir(parents=True, exist_ok=True)
    LEARNED.write_text(key + "\n")
    print(f"learned {key} (code {code}) -> {LEARNED}")
    print("That key now wakes Gideon; it no longer does whatever it used to do.")
    return code


def resolve_keys(names: list[str]) -> set[int]:
    codes = set()
    for name in names:
        code = getattr(ecodes, name.strip().upper(), None)
        if not isinstance(code, int):
            sys.exit(f"unknown key name {name!r} - use the KEY_* name printed by "
                     f"confirm_keycode.py")
        codes.add(code)
    return codes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gideon-hotkey", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default=os.environ.get("GIDEON_HOTKEY_DEVICE", ""),
                    help="substring of the keyboard's name (case-insensitive)")
    ap.add_argument("--keys", default=os.environ.get("GIDEON_HOTKEY_KEYS", ""),
                    help="comma-separated KEY_* names to capture "
                         f"(default: whatever --learn recorded, else {FALLBACK_KEYS})")
    ap.add_argument("--learn", action="store_true",
                    help="press the button once; remember its keycode and exit")
    ap.add_argument("--command", default=os.environ.get("GIDEON_TRIGGER_CMD", DEFAULT_COMMAND),
                    help="command run on key-down")
    ap.add_argument("--no-forward", action="store_true",
                    help="do not replay the other keys through /dev/uinput")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", stream=sys.stderr)
    if not args.device:
        sys.exit("no device name given: pass --device or set GIDEON_HOTKEY_DEVICE "
                 "(run discover_devices.py to find it)")

    if args.learn:
        learn_key(args.device)
        return 0

    # --keys wins, then whatever --learn recorded, then the usual mute key.
    if args.keys:
        source, names = "--keys/env", args.keys
    elif LEARNED.is_file() and LEARNED.read_text().strip():
        source, names = str(LEARNED), LEARNED.read_text().strip()
    else:
        source, names = "default", FALLBACK_KEYS
    codes = resolve_keys(names.split(","))
    log.debug("trigger key from %s: %s", source, names)
    trigger = AgentTrigger(args.command)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Step 5 of the plan: the device may be absent at boot and may vanish at any
    # moment, so "wait for it" is the normal state, not an error path.
    waiting = False
    while not _stop:
        path = resolve_by_name(args.device, require_key=next(iter(codes)))
        if path is None:
            if not waiting:
                log.info("waiting for a device named like %r ... %s", args.device,
                         permission_hint() or "")
                waiting = True
            time.sleep(RETRY_S)
            continue
        waiting = False
        try:
            pump(InputDevice(path), codes, trigger, forward=not args.no_forward)
        except OSError as exc:
            if exc.errno not in (errno.ENODEV, errno.ENOENT, errno.EIO, errno.EBUSY):
                raise
            log.info("keyboard disconnected (%s); waiting for it to come back",
                     errno.errorcode.get(exc.errno, exc.errno))
            time.sleep(RETRY_S)

    trigger.shutdown()
    log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
