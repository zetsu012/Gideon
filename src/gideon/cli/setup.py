"""Interactive setup, exposed as `gideon --setup` and `gideon --setup-key`.

Everything a fresh install needs, in the command the user already has. There is
deliberately no shell script and no separate repository checkout: the .deb
carries these modules, so `gideon --setup` is the whole story on a new machine.

The keyboard half shells out to the SYSTEM python. python3-evdev is an apt
package and is not in the vendored runtime, so `gideon.hotkey.*` can never be
imported here - only executed as scripts.
"""
from __future__ import annotations
import grp, os, shlex, shutil, subprocess, sys
from pathlib import Path

from ..core.config import Config
from ..ipc import control

SYSTEM_PY = "/usr/bin/python3"
HOTKEY_DIR = Path(__file__).resolve().parent.parent / "hotkey"
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
HOTKEY_UNIT = UNIT_DIR / "gideon-hotkey.service"
UDEV_RULE = Path("/etc/udev/rules.d/99-uinput.rules")

BOLD, DIM, GREEN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[0m"


def say(msg: str) -> None:   print(f"\n{BOLD}==> {msg}{RESET}")
def ok(msg: str) -> None:    print(f"    {GREEN}✓{RESET} {msg}")
def warn(msg: str) -> None:  print(f"    {YELLOW}!{RESET} {msg}")
def info(msg: str) -> None:  print(f"    {msg}")


def ask(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"    {question} {suffix} ").strip().lower()
    except EOFError:
        return default
    return default if not answer else answer.startswith("y")


def run(argv: list[str], *, sudo: bool = False, quiet: bool = True) -> bool:
    if sudo and os.geteuid() != 0:
        argv = ["sudo", *argv]
    info(f"{DIM}$ {' '.join(shlex.quote(a) for a in argv)}{RESET}")
    out = subprocess.DEVNULL if quiet else None
    return subprocess.call(argv, stdout=out, stderr=out) == 0


def in_input_group() -> bool:
    try:
        return grp.getgrnam("input").gr_gid in os.getgroups()
    except KeyError:
        return False


def as_input(argv: list[str], **kwargs):
    """Run with the 'input' group applied even when this login session predates
    the usermod - otherwise setup always needs a logout to get past step one."""
    if not in_input_group():
        argv = ["sg", "input", "-c", " ".join(shlex.quote(a) for a in argv)]
    return subprocess.run(argv, text=True, **kwargs)


def systemctl(*args: str, quiet: bool = True) -> bool:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.call(["systemctl", "--user", *args], stdout=out, stderr=out) == 0


# --------------------------------------------------------------------------- #
# gideon --setup
# --------------------------------------------------------------------------- #
def check_models(cfg: Config) -> bool:
    say("Checking models")
    missing = [p for p in (cfg.vad_path, cfg.voice_path, cfg.whisper_dir) if not p.exists()]
    for path in (cfg.vad_path, cfg.voice_path, cfg.whisper_dir):
        (ok if path.exists() else warn)(str(path))
    if missing:
        warn("Models are baked into the .deb; a missing one means a broken install.")
        return False
    return True


def check_audio() -> bool:
    """PortAudio is the one library the package cannot vendor: sounddevice
    dlopen()s the system copy. apt installs it as a dependency, so a failure
    here means a broken install or a session with no audio at all."""
    say("Checking audio")
    for attempt in (1, 2):
        try:
            import importlib
            import sounddevice
            importlib.reload(sounddevice)     # pick up a library installed just now
            sounddevice.query_devices()
        except OSError as exc:                # dlopen failure: the library is absent
            if attempt == 2:
                warn(f"PortAudio still not usable: {exc}")
                return False
            warn(f"PortAudio not usable: {exc}")
            if not ask("Install libportaudio2 with apt?"):
                return False
            run(["apt-get", "install", "-y", "libportaudio2"], sudo=True, quiet=False)
        except Exception as exc:              # present, but no devices to enumerate
            warn(f"audio devices unavailable: {exc}")
            info("Run this inside your desktop session, not over a bare ssh login.")
            return False
        else:
            ok("PortAudio present, devices enumerated")
            return True
    return False


def start_daemon() -> bool:
    """Enable and start the always-on daemon, then prove it is answering."""
    say("The always-on daemon")
    if not shutil.which("systemctl"):
        warn("no systemctl - start it yourself with:  gideon")
        return False
    if not systemctl("cat", "gideon.service"):
        warn("gideon.service is not installed (running from a source checkout?)")
        info("Start it by hand in another terminal:  ./scripts/run-local.sh")
        return False
    systemctl("enable", "--now", "gideon.service")
    state = subprocess.run(["systemctl", "--user", "is-active", "gideon.service"],
                           capture_output=True, text=True).stdout.strip()
    if state != "active":
        warn(f"gideon.service is {state}")
        info("journalctl --user -u gideon -e")
        return False
    ok("gideon.service is active and listening for the wake phrase")

    # The socket is what a key press talks to, so its absence is worth catching
    # here rather than as a mysteriously dead key later.
    for _ in range(20):                       # models take a few seconds to load
        if control.send("ping"):
            ok(f"control socket ready ({control.default_path()})")
            return True
        import time; time.sleep(0.5)
    warn(f"no control socket at {control.default_path()} after 10s")
    info("The key will still work, but by starting a slow one-shot per press.")
    return False


def setup(cfg: Config) -> int:
    print(f"\n{BOLD}Gideon setup{RESET}")
    healthy = check_models(cfg)
    healthy &= check_audio()
    if not healthy:
        warn("Fix the above, then re-run:  gideon --setup")
        return 1
    start_daemon()
    setup_indicator()

    say("Push-to-talk key (optional)")
    info("A key on an external keyboard can stand in for the wake phrase: press")
    info("it and just talk. It arms the daemon above - it does not start a")
    info("second one, and 'hey gideon' keeps working either way.")
    if not ask("Set up a key now?", default=True):
        info("Later:  gideon --setup-key")
        return 0
    return setup_key(cfg)


def setup_indicator() -> bool:
    """Offer the tray indicator.

    A daemon with no window is indistinguishable from a dead one, so this is
    part of the ordinary setup rather than an extra. It is still optional: the
    GTK bindings are apt packages that a headless box has no reason to carry,
    and Gideon answers exactly the same without them.
    """
    say("Tray indicator (recommended)")
    info("A tray icon that shows whether Gideon is running and what he is doing")
    info("right now, plus a health panel with one row per subsystem.")
    from . import ui as ui_mod
    if not ui_mod.have_gtk():
        info("It needs GTK from apt: " + " ".join(ui_mod.APT_PACKAGES))
        if not ask("Install them?"):
            info("Later:  sudo apt install " + " ".join(ui_mod.APT_PACKAGES))
            return False
        run(["apt-get", "install", "-y", *ui_mod.APT_PACKAGES], sudo=True, quiet=False)
        if not ui_mod.have_gtk():
            warn("GTK still unavailable; skipping the indicator")
            return False
    ok("GTK available")
    if not systemctl("cat", "gideon-ui.service"):
        # Source checkout: there is no unit to enable, but the command works.
        info("running from a checkout - start it with:  gideon --ui")
        return True
    systemctl("enable", "--now", "gideon-ui.service")
    if systemctl("is-active", "--quiet", "gideon-ui.service"):
        ok("indicator running - look for the microphone icon in the tray")
    else:
        warn("indicator did not start:  journalctl --user -u gideon-ui -e")
    return True


# --------------------------------------------------------------------------- #
# gideon --setup-key
# --------------------------------------------------------------------------- #
def ensure_evdev() -> bool:
    say("Checking python3-evdev")
    probe = [SYSTEM_PY, "-c", "import evdev"]
    if subprocess.call(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
        ok("already installed")
        return True
    info("The key listener runs on the system python and needs python3-evdev.")
    if not ask("Install it with apt?"):
        return False
    run(["apt-get", "install", "-y", "python3-evdev"], sudo=True, quiet=False)
    return subprocess.call(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def ensure_input_group() -> bool:
    """Returns True if a re-login is needed before the service can start."""
    say("Checking 'input' group membership")
    user = os.environ.get("USER") or os.getlogin()
    try:
        members = grp.getgrnam("input").gr_mem
    except KeyError:
        members = []
    if user in members:
        ok(f"{user} is in the group")
        return not in_input_group()      # in the group, but not in THIS session
    run(["usermod", "-aG", "input", user], sudo=True, quiet=False)
    ok(f"added {user} to 'input'")
    return True


def ensure_uinput() -> None:
    """Without /dev/uinput the grabbed keyboard stops typing entirely, because
    the listener cannot replay the keys it is not consuming."""
    say("Checking /dev/uinput access")
    probe = [SYSTEM_PY, "-c", "open('/dev/uinput','wb').close()"]
    if as_input(probe, capture_output=True).returncode == 0:
        ok("writable")
        return
    info("Installing a udev rule so the 'input' group may write to it.")
    subprocess.run(["sudo", "tee", str(UDEV_RULE)], input='KERNEL=="uinput", GROUP="input", MODE="0660"\n',
                   text=True, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "tee", "/etc/modules-load.d/uinput.conf"], input="uinput\n",
                   text=True, stdout=subprocess.DEVNULL)
    run(["modprobe", "uinput"], sudo=True)
    run(["udevadm", "control", "--reload"], sudo=True)
    run(["udevadm", "trigger"], sudo=True)
    ok("udev rule installed")


def pick_keyboard() -> str | None:
    say("Pick the keyboard whose key should wake Gideon")
    result = as_input([SYSTEM_PY, str(HOTKEY_DIR / "list_keyboards.py")], capture_output=True)
    names = [n for n in result.stdout.splitlines() if n.strip()]
    if not names:
        warn(result.stderr.strip() or "no keyboards found - connect it and re-run")
        return None
    for i, name in enumerate(names, 1):
        info(f"{i}) {name}")
    try:
        choice = int(input("    number: ").strip())
        return names[choice - 1]
    except (ValueError, IndexError, EOFError):
        warn("invalid choice")
        return None


def learn_key(device: str) -> bool:
    """Record the trigger key, with the listener stood down.

    An already-running listener holds an exclusive grab on the keyboard, so its
    events reach that process and nothing else. Learning would then wait forever
    on a key press it can never see - which is exactly what happens the second
    time someone runs this, to change their key. So stop it first, and put it
    back if the learning step does not succeed.
    """
    was_running = systemctl("is-active", "--quiet", "gideon-hotkey.service")
    if was_running:
        info("stopping the running key listener so it releases the keyboard")
        systemctl("stop", "gideon-hotkey.service")
    say("Press the key you want to use")
    info("It is recorded, not consumed - it still mutes until the service runs.")
    learned = as_input([SYSTEM_PY, str(HOTKEY_DIR / "listener.py"),
                        "--device", device, "--learn"]).returncode == 0
    if not learned and was_running:
        # Leave the machine as we found it; install_unit() starts it again on
        # the success path.
        systemctl("start", "gideon-hotkey.service")
        info("restarted the previous key listener")
    return learned


def trigger_command() -> str:
    """What a press falls back to when no daemon is listening."""
    installed = shutil.which("gideon")
    if installed:
        return f"{installed} --once"
    local = HOTKEY_DIR.parent.parent.parent / "scripts" / "run-local.sh"       # source checkout
    return f"{local} --once"


UNIT_TEMPLATE = """\
[Unit]
Description=Gideon hotkey listener (keyboard button -> voice agent)
After=graphical-session.target

[Service]
Type=simple
# Quoted: systemd splits an unquoted Environment= on whitespace, and device
# names contain spaces.
Environment="GIDEON_HOTKEY_DEVICE={device}"
# Empty: use whatever `gideon --setup-key` recorded in ~/.config/gideon/hotkey-key.
Environment="GIDEON_HOTKEY_KEYS="
Environment="GIDEON_TRIGGER_CMD={trigger}"
ExecStart={python} {listener}
# The keyboard is often absent at login and comes and goes; the listener polls
# for it by name itself, so this only covers real crashes.
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
"""


def install_unit(device: str, relogin: bool) -> None:
    say("Installing the key listener service")
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    HOTKEY_UNIT.write_text(UNIT_TEMPLATE.format(
        device=device, trigger=trigger_command(),
        python=SYSTEM_PY, listener=HOTKEY_DIR / "listener.py"))
    ok(str(HOTKEY_UNIT))
    systemctl("daemon-reload")
    if relogin:
        systemctl("enable", "gideon-hotkey.service")
        warn("Log out and back in to finish.")
        info("Group membership is fixed at login, so the systemd user manager")
        info("cannot read /dev/input/event* until you do. The service is enabled")
        info("and will start itself then.")
    else:
        systemctl("enable", "--now", "gideon-hotkey.service")
        ok("running - press your key")
    info("Logs:  journalctl --user -u gideon-hotkey -f")


def setup_key(cfg: Config) -> int:
    if not HOTKEY_DIR.is_dir():
        warn(f"hotkey modules missing at {HOTKEY_DIR}")
        return 1
    if not ensure_evdev():
        return 1
    relogin = ensure_input_group()
    ensure_uinput()
    device = pick_keyboard()
    if device is None:
        return 1
    if not learn_key(device):
        return 1
    install_unit(device, relogin)
    return 0
