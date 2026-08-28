# `packaging/launcher/gideon.launcher`

Installed as **`/usr/bin/gideon`** — the command users and the systemd unit run.

A `/bin/sh` script, not a Python entry point, because it has to set the environment before
any interpreter starts.

```sh
exec "$GIDEON_HOME/python/bin/python3" -E -s -c '<bootstrap>' "$@"
```

`-E -s` is the point of the file: it discards `PYTHONPATH` and `~/.local` site-packages, so
a stray user environment can never shadow the vendored numpy/onnxruntime with an
incompatible build. Because `-E` also discards `PYTHONPATH`, the vendored `lib/` and `app/`
directories are injected into `sys.path` **explicitly** by the inline bootstrap, which then
calls `runpy.run_module("gideon", run_name="__main__")`.

| Set | Value |
|---|---|
| `GIDEON_HOME` | `/opt/gideon` unless overridden |
| `PYTHONDONTWRITEBYTECODE` | `1` — `/opt` is read-only to the daemon |
| `OMP_NUM_THREADS` | `4` unless overridden — caps CTranslate2 threading |
| `TOKENIZERS_PARALLELISM` | `false` — silences the fork warning |
| `HF_HUB_OFFLINE` | `1` (via `setdefault`) — models are baked in, never fetched |

`sys.argv[0]` is set to `gideon` so `--help` reads correctly.

`scripts/run-local.sh` mirrors this bootstrap with `src/` prepended; changes here usually
belong there too.
