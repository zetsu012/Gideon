# `scripts/run-local.sh`

**Run the working copy — no .deb, no sudo, no install.**

```bash
./scripts/run-local.sh                 # the daemon
./scripts/run-local.sh --selftest      # models + invariants; works without PortAudio
./scripts/run-local.sh --say "hi"      # speaker smoke test
./scripts/run-local.sh --once -v       # one utterance, verbose
./scripts/run-local.sh --setup         # interactive install check
```

It reuses the vendored runtime and models that `scripts/build-deb.sh` staged into
`build/stage`, but puts **`src/` first on `sys.path`**, so edits take effect on the next run
with no rebuild. Requires that a build has been done at least once.

## What it sets

| | |
|---|---|
| `GIDEON_HOME` | `build/stage/opt/gideon` — where models and vendored libs are found |
| `GIDEON_CONFIG` | `packaging/config/config.toml` unless already set |
| `GIDEON_SRC` | `src` — injected ahead of `lib/` and `app/` |
| `HF_HUB_OFFLINE=1`, `TOKENIZERS_PARALLELISM=false`, `OMP_NUM_THREADS=4` | offline, quiet, bounded |

Python runs with `-E -s`, so `sys.path` is injected explicitly by the inline bootstrap
rather than through `PYTHONPATH` — a stray environment or a `~/.local` site-packages must
never shadow the vendored numpy/onnxruntime.

## The PortAudio pre-flight

`sounddevice` `dlopen()`s the system PortAudio, the one library not vendored. The script
checks `ldconfig` and stops with `sudo apt install libportaudio2` — except for `--selftest`,
which opens no device and is allowed through. The .deb declares the dependency, so only
this run-from-source path needs it by hand.
