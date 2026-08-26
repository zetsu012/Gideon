# Gideon documentation

Always-on, fully offline voice assistant for Ubuntu. Wake detection, speech recognition
and speech synthesis all run locally on the CPU.

## Start here

| Document | Read it for |
|---|---|
| [`../README.md`](../README.md) | install, usage, troubleshooting |
| [`STRUCTURE.md`](STRUCTURE.md) | the folder layout and why the boundaries fall where they do |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | how a spoken sentence becomes a spoken reply |
| [`DEPENDENCIES.md`](DEPENDENCIES.md) | every dependency: vendored, apt-installed, or manual |
| [`PLAN.md`](PLAN.md) | why it is built this way, the roadmap, and measurements that changed the design |
| [`HOTKEY.md`](HOTKEY.md) | push-to-talk: design and setup |
| [`INDICATOR.md`](INDICATOR.md) | the tray icon, the HUD and the health panel |
| [`NEW-SYSTEM-SETUP.md`](NEW-SYSTEM-SETUP.md) | installing on a fresh machine |
| [`reference/`](reference/README.md) | **one document per file** — purpose, API, invariants |

## Common tasks

| Task | Where |
|---|---|
| Change a setting | [`reference/src/gideon/core/config.md`](reference/src/gideon/core/config.md) |
| Understand why it did not answer | `ARCHITECTURE.md` §6, and the `WAKE`/`FOLLOW`/`KEY`/`----` log tags in [`reference/src/gideon/__main__.md`](reference/src/gideon/__main__.md) |
| Add a dependency | [`DEPENDENCIES.md`](DEPENDENCIES.md) §8 |
| Build the package | [`reference/scripts/build-deb.md`](reference/scripts/build-deb.md) |
| Run without installing | [`reference/scripts/run-local.md`](reference/scripts/run-local.md) |
| Wire up a key | [`HOTKEY.md`](HOTKEY.md), [`reference/src/gideon/hotkey/listener.md`](reference/src/gideon/hotkey/listener.md) |
| See whether Gideon is running | `gideon --ui --health`, or [`INDICATOR.md`](INDICATOR.md) |
| Add a subsystem to the health panel | [`reference/src/gideon/core/state.md`](reference/src/gideon/core/state.md) — one `health_set()` call is enough |

## Conventions

- Every source file has a document at the same relative path under `reference/`.
- There is no test suite; `--selftest` is the check. New invariants are asserted there.
- Application edits need no rebuild — `scripts/run-local.sh` puts `src/` first on the path.
