# `requirements/`

Four manifests, so that "what does this need" is answerable without reading a build script.
Narrative version: **`docs/DEPENDENCIES.md`**.

| File | Contents | Consumed by |
|---|---|---|
| `python-runtime.txt` | the 4 direct Python deps vendored into the .deb | **read by `scripts/build-deb.sh`** — this file is live, not documentation |
| `python-locked.txt` | the full resolved closure actually shipped (28 packages) | generated after a build; recorded so the package contents are auditable |
| `python-optional.txt` | packages deliberately **not** installed, with the reason | nothing — a decision on record |
| `system-apt.txt` | apt packages, mirroring `Depends:`/`Recommends:` | nothing — mirrors `packaging/debian/control`, keep in sync |
| `build-tools.txt` | tools needed on the machine that builds the .deb | mirrors the `need` checks in `build-deb.sh` |

`python-runtime.txt` is intentionally **unpinned**. The build resolves the closure once and
bakes it in, so the shipped artifact is fixed even though the manifest is not; hand-pinning
a `--no-deps` list breaks whenever an upstream adds a transitive dependency.

Regenerate the lock after a build:

```bash
ls build/stage/opt/gideon/lib | grep dist-info | sed 's/\.dist-info//' | sort
```
