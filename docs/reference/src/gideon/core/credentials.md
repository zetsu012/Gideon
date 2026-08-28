# `src/gideon/core/credentials.py`

**API keys, kept out of the config file.** Reads and writes
`~/.config/gideon/credentials.toml`, one section per provider.

## Why not just put the key in config.toml

`/etc/gideon/config.toml` is a dpkg **conffile**: world-readable, system-wide, shared by
every user on the machine, and precisely the file someone pastes into a bug report. A
secret does not belong there. The per-user credentials file is created **0600**, and by
`os.open(..., 0o600)` rather than write-then-chmod — the latter leaves a window in which
the key sits on disk readable by everyone.

An existing file with loose permissions produces a **warning, not a refusal**: locking a
user out of their own assistant over a file mode would be a worse failure than the one
being reported. `--selftest` asserts the mode on files this code writes.

## Environment wins over the file

`CEREBRAS_API_KEY` / `OPENROUTER_API_KEY` override the stored value when set, for people
who keep secrets in a systemd drop-in or a password-manager shell hook. `gideon
--provider` says so when it notices one, because otherwise the key it just saved would
appear to be ignored.

`save_api_key()` preserves other providers' keys, so configuring a second provider does
not silently evict the first.

| | |
|---|---|
| Imports | stdlib only |
| Imported by | `llm/__init__`, `cli/provider` |
| File | `~/.config/gideon/credentials.toml` (0600) |
