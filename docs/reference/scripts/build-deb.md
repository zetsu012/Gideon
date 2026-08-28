# `scripts/build-deb.sh`

**Builds the entire product: `build/gideon_<version>_amd64.deb`.**

```bash
./scripts/build-deb.sh                       # defaults
VERSION=0.2.0 WHISPER_MODEL=base.en ./scripts/build-deb.sh
```

Env knobs: `VERSION`, `WHISPER_MODEL` (`tiny.en`), `VOICE` (`en_US-lessac-medium`),
`BUILD_DIR`. Build-host tools are checked up front and named on failure —
see `requirements/build-tools.txt`.

## Stages

1. **Vendor CPython 3.12**, relocatable, via `uv python install`. Copied with `cp -aL` so
   uv's symlinks cannot escape the package. `test`, `idlelib`, `tkinter`, `ensurepip`,
   `turtledemo`, `lib2to3` and `share` are removed — a headless daemon never uses them.
2. **Resolve dependencies** into `opt/gideon/lib` from `requirements/python-runtime.txt`.
   The **full transitive closure** is resolved and then pruned. A hand-pinned `--no-deps`
   list is explicitly rejected: it breaks the moment an upstream adds a transitive dep.
3. **Fetch models** — the Piper voice and the Whisper snapshot through their own libraries;
   Silero VAD by `curl` from a pinned upstream tag, **SHA-256 verified, build aborts on
   mismatch** (see `docs/reference/src/gideon/speech/vad.md` for why v4 specifically).
4. **Prune** `scipy`, `scipy.libs`, `sklearn`, `hf_xet` and report the MB saved.
   `av` deliberately **stays**: `faster_whisper/audio.py` imports it unconditionally at
   package-import time even though this pipeline feeds `transcribe()` numpy arrays.
5. **Strip** every vendored `.so`.
6. **Stage the app** — `src/gideon` verbatim into `opt/gideon/app/gideon`, plus
   `chmod 0755` on `hotkey/*.py` so those stay executable by the system python.
7. **Assemble** — `packaging/config/config.toml` → `/etc/gideon/`,
   `packaging/launcher/gideon.launcher` → `/usr/bin/gideon`,
   `packaging/systemd/gideon.service` → `/usr/lib/systemd/user/`, and `debian/control`
   with `@VERSION@`/`@ARCH@`/`@SIZE@` substituted from the measured staging tree.
8. **`fakeroot dpkg-deb -Zzstd -z19`**.

`build/` is generated, gitignored, and safe to delete. Re-run this only when dependencies
or models change — application edits do not need a rebuild, that is what `run-local.sh` is
for.
