"""`gideon --provider`: choose where Tier 1 answers come from.

Walks through picking a provider, pasting a key, choosing a model from the
provider's live catalogue and asking it a test question, then writes the key to
~/.config/gideon/credentials.toml (0600) and the choice to the user config.

Two things here are less obvious than they look:

**Writing the user config shadows /etc entirely.** `Config.load()` takes the
first file that exists and does not merge, so creating
~/.config/gideon/config.toml would silently revert every other setting in
/etc/gideon/config.toml to its default. So if the user config does not exist yet,
it is seeded as a copy of the system one before anything is changed.

**The settings are appended in their own marked block** rather than edited into
the existing [llm] section. Section names do not matter to `Config.load()` - it
flattens one level of any section - and later keys win, so a self-contained block
at the end is both simpler to rewrite idempotently and impossible to half-apply.
"""
from __future__ import annotations
import getpass, os, subprocess, time
from pathlib import Path

from ..core.config import Config, CONFIG_PATHS
from ..core import credentials
from ..llm import provider as providers
from ..llm.cloud import CloudLLM, list_models

BOLD, DIM, GREEN, YELLOW, RED, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")

USER_CONFIG = Path(os.path.expanduser("~/.config/gideon/config.toml"))
# The service is firewalled to localhost (IPAddressAllow=localhost,
# IPAddressDeny=any) because Gideon was built to be offline. Whether systemd
# actually enforces that for a *user* unit depends on BPF cgroup delegation, so
# on some machines a cloud provider "just works" and on others every request
# fails as unreachable - the same symptom as a bad key. Rather than leave that
# to chance, choosing a cloud provider installs a drop-in that opens outbound
# access, and choosing Ollama removes it again.
DROPIN = Path(os.path.expanduser(
    "~/.config/systemd/user/gideon.service.d/10-cloud-provider.conf"))
DROPIN_BODY = """\
# Written by `gideon --provider` when a cloud provider was selected.
# gideon.service denies all non-localhost traffic; a cloud provider needs it back.
# Removed automatically by `gideon --provider` when you switch back to Ollama.
[Service]
IPAddressDeny=
IPAddressAllow=any
"""
SYSTEM_CONFIG = Path("/etc/gideon/config.toml")

BEGIN = "# >>> gideon --provider >>>"
END = "# <<< gideon --provider <<<"

# OpenRouter lists thousands of models and most are useless for speech. These are
# the substrings worth showing unprompted; anything else is reachable by typing a
# search term or the exact id.
SUGGEST_HINTS = ("llama-3.3", "llama-3.1", "llama3.1", "llama3.3",
                 "gemma", "mistral", "gpt-oss", "qwen")


def say(msg: str) -> None:   print(f"\n{BOLD}==> {msg}{RESET}")
def ok(msg: str) -> None:    print(f"    {GREEN}✓{RESET} {msg}")
def warn(msg: str) -> None:  print(f"    {YELLOW}!{RESET} {msg}")
def bad(msg: str) -> None:   print(f"    {RED}✗{RESET} {msg}")
def info(msg: str) -> None:  print(f"    {msg}")


def _prompt(question: str, default: str = "") -> str:
    suffix = f" {DIM}[{default}]{RESET}" if default else ""
    try:
        answer = input(f"    {question}{suffix}: ").strip()
    except EOFError:
        return default
    return answer or default


def _choose_provider(cfg: Config) -> str | None:
    say("Where should Gideon's answers come from?")
    options = [
        (providers.LOCAL, "Ollama (local)",
         "fully offline, nothing leaves this machine - the default"),
    ]
    for p in providers.PROVIDERS.values():
        options.append((p.key, f"{p.label} (cloud)", p.hint))
    for i, (key, label, hint) in enumerate(options, 1):
        marker = f" {GREEN}(current){RESET}" if key == cfg.llm_provider else ""
        print(f"    {i}. {BOLD}{label}{RESET}{marker}\n       {DIM}{hint}{RESET}")
    print()
    warn("A cloud provider sends your transcribed speech to that company.")
    info(f"{DIM}Wake detection, speech-to-text and the voice stay on this machine "
         f"either way.{RESET}")
    raw = _prompt("choose", "1")
    try:
        return options[int(raw) - 1][0]
    except (ValueError, IndexError):
        bad(f"{raw!r} is not one of the choices")
        return None


def _get_key(prov) -> str | None:
    existing = credentials.api_key(prov)
    if existing:
        say(f"An API key for {prov.label} is already stored")
        info(f"{DIM}...{existing[-4:]}{RESET}")
        if _prompt("keep it? (y/n)", "y").lower().startswith("y"):
            return existing
    say(f"Paste your {prov.label} API key")
    info(f"Get one at {prov.signup}")
    info(f"{DIM}Input is hidden. It is stored in {credentials.PATH} (mode 0600).{RESET}")
    if os.environ.get(prov.env_var):
        warn(f"{prov.env_var} is set in this environment and overrides the file.")
    try:
        key = getpass.getpass("    key: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not key:
        bad("no key entered")
        return None
    return key


def _choose_model(prov, key: str, current: str) -> str | None:
    say(f"Fetching the {prov.label} catalogue")
    try:
        models = list_models(prov, key)
    except Exception as e:                          # noqa: BLE001 - shown to the user
        bad(f"could not list models: {type(e).__name__}: {e}")
        info("The key may be wrong, or the network is down.")
        # Not fatal: the user may know exactly which model they want.
        typed = _prompt("model id to use anyway (blank to abort)", current or prov.suggested)
        return typed or None
    ok(f"{len(models)} models available")

    shortlist = [m for m in models if any(h in m.lower() for h in SUGGEST_HINTS)]
    default = current or (prov.suggested if prov.suggested in models else
                          (shortlist[0] if shortlist else models[0]))

    while True:
        shown = shortlist[:15] if shortlist else models[:15]
        print()
        for i, m in enumerate(shown, 1):
            marker = f" {GREEN}(suggested){RESET}" if m == prov.suggested else ""
            print(f"    {i:2}. {m}{marker}")
        if len(models) > len(shown):
            info(f"{DIM}...and {len(models) - len(shown)} more. "
                 f"Type part of a name to search, or paste an exact id.{RESET}")
        info(f"{DIM}Avoid reasoning models (r1, thinking, o1): they spend their whole "
             f"budget on chain-of-thought and answer too slowly for speech.{RESET}")
        raw = _prompt("number, search term, or model id", default)
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(shown):
            return shown[int(raw) - 1]
        if raw in models:
            return raw
        matches = [m for m in models if raw.lower() in m.lower()]
        if not matches:
            bad(f"nothing matches {raw!r}")
            continue
        if len(matches) == 1:
            return matches[0]
        shortlist = matches


def _test(prov, model: str, key: str, timeout: float) -> bool:
    say(f"Asking {model} a test question")
    client = CloudLLM(prov, model, key, timeout=timeout)
    t0 = time.time()
    reply = client.ask("In one short sentence, what is the capital of France?")
    elapsed = time.time() - t0
    if not reply:
        bad("no usable answer (see the warnings above)")
        return False
    ok(f'"{reply}"  {DIM}({elapsed:.1f}s){RESET}')
    if elapsed > 4.0:
        warn(f"{elapsed:.1f}s is slow for speech; a smaller model would feel better.")
    return True


def _write_config(updates: dict) -> Path:
    """Rewrite the managed block in the user config, seeding the file if new."""
    if not USER_CONFIG.exists():
        USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        if SYSTEM_CONFIG.is_file():
            # Config.load() does not merge - the first file found wins entirely -
            # so a user config containing only these keys would silently reset
            # every other setting to its built-in default.
            USER_CONFIG.write_text(SYSTEM_CONFIG.read_text())
        else:
            USER_CONFIG.write_text("# Gideon user configuration.\n")

    text = USER_CONFIG.read_text()
    if BEGIN in text and END in text:
        head, _, rest = text.partition(BEGIN)
        _, _, tail = rest.partition(END)
        text = head.rstrip() + "\n" + tail.lstrip("\n")

    block = [BEGIN,
             "# Written by `gideon --provider`. Edit by re-running it.",
             "# These keys are last in the file on purpose: Config.load() flattens",
             "# every section and later keys win, so this block is authoritative.",
             "[provider]"]
    for k, v in updates.items():
        block.append(f'{k} = "{v}"' if isinstance(v, str) else f"{k} = {v}")
    block.append(END)
    USER_CONFIG.write_text(text.rstrip() + "\n\n" + "\n".join(block) + "\n")
    return USER_CONFIG


def _network_access(enable: bool) -> None:
    """Open or re-close the daemon's outbound network access."""
    try:
        if enable:
            DROPIN.parent.mkdir(parents=True, exist_ok=True)
            DROPIN.write_text(DROPIN_BODY)        # idempotent
            ok(f"allowed outbound network for the service {DIM}({DROPIN.name}){RESET}")
        elif DROPIN.exists():
            DROPIN.unlink()
            ok(f"removed {DROPIN.name} - the service is localhost-only again")
        else:
            return
        subprocess.run(["systemctl", "--user", "daemon-reload"],
                       check=False, capture_output=True)
    except OSError as e:
        # Never fatal: the settings are already written and the drop-in only
        # matters on systems that enforce the filter for user units.
        warn(f"could not update {DROPIN}: {e}")


def configure(cfg: Config) -> int:
    print(f"\n{BOLD}Gideon — Tier 1 provider{RESET}")
    info(f"{DIM}Currently: {cfg.llm_provider}"
         f"{' ' + cfg.cloud_model if cfg.cloud_model else ''}{RESET}")

    choice = _choose_provider(cfg)
    if choice is None:
        return 1

    if choice == providers.LOCAL:
        path = _write_config({"llm_provider": providers.LOCAL})
        say("Using the local model")
        ok(f"wrote {path}")
        _network_access(False)
        info(f"Ollama serves {cfg.llm_model} at {cfg.llm_url}.")
        info("Restart to apply:  systemctl --user restart gideon")
        return 0

    prov = providers.get(choice)
    key = _get_key(prov)
    if key is None:
        return 1
    model = _choose_model(prov, key, cfg.cloud_model)
    if model is None:
        bad("no model chosen; nothing was written")
        return 1
    if not _test(prov, model, key, cfg.cloud_timeout):
        if not _prompt("save this configuration anyway? (y/n)", "n").lower().startswith("y"):
            info("nothing was written")
            return 1

    cred_path = credentials.save_api_key(prov, key)
    path = _write_config({"llm_provider": prov.key, "cloud_model": model})
    say("Saved")
    _network_access(True)
    ok(f"key   → {cred_path} {DIM}(mode 0600){RESET}")
    ok(f"choice → {path}")
    info(f"If {prov.label} is unreachable, Gideon falls back to the local model "
         f"({cfg.llm_model}), then to canned replies.")
    info("Restart to apply:  systemctl --user restart gideon")
    return 0
