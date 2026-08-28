"""API keys, kept out of the config file.

`/etc/gideon/config.toml` is a dpkg conffile: world-readable, system-wide, and
exactly the file someone pastes into a bug report. Keys therefore live in their
own per-user file, created 0600:

    ~/.config/gideon/credentials.toml

        [cerebras]
        api_key = "csk-..."

An environment variable (CEREBRAS_API_KEY, OPENROUTER_API_KEY) overrides the
file when set, for people who would rather keep secrets in a systemd drop-in or
a password manager's shell hook.
"""
from __future__ import annotations
import logging, os, stat, tomllib
from pathlib import Path

log = logging.getLogger("gideon.credentials")

PATH = Path(os.path.expanduser("~/.config/gideon/credentials.toml"))


def _load() -> dict:
    if not PATH.is_file():
        return {}
    try:
        mode = PATH.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            # Warn rather than refuse: locking the user out of their own
            # assistant over file permissions would be a worse failure than the
            # one being reported.
            log.warning("%s is readable by other users; fix with: chmod 600 %s",
                        PATH, PATH)
        with PATH.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, ValueError) as e:
        log.warning("could not read %s (%s); treating it as empty", PATH, e)
        return {}


def api_key(provider) -> str:
    """The key for a provider: environment first, then the file, then empty."""
    from_env = os.environ.get(provider.env_var, "").strip()
    if from_env:
        return from_env
    section = _load().get(provider.key) or {}
    return str(section.get("api_key", "")).strip()


def save_api_key(provider, key: str) -> Path:
    """Write one provider's key, preserving any others already stored."""
    data = _load()
    data.setdefault(provider.key, {})["api_key"] = key
    PATH.parent.mkdir(parents=True, exist_ok=True)
    # Create with the right mode from the start: writing then chmod-ing leaves a
    # window where the key is on disk world-readable.
    fd = os.open(PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("# Gideon API keys. Keep this file mode 0600.\n"
                 "# Written by `gideon --provider`.\n\n")
        for name, section in sorted(data.items()):
            value = str((section or {}).get("api_key", ""))
            if value:
                fh.write(f'[{name}]\napi_key = "{value}"\n\n')
    os.chmod(PATH, 0o600)      # in case the file already existed
    return PATH
