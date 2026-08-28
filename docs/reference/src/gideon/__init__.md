# `src/gideon/__init__.py`

**Package root.** Holds one thing: `__version__ = "0.1.0"`.

Kept empty of logic on purpose — importing `gideon` must stay free. The daemon is
started with `runpy.run_module("gideon", run_name="__main__")` by both the installed
launcher and `scripts/run-local.sh`, so anything expensive here would be paid on every
invocation including `--say` and `--setup`.

| | |
|---|---|
| Imports | nothing |
| Imported by | every module in the package |
| Change it when | the version bumps (keep in step with `VERSION=` in `scripts/build-deb.sh`) |
