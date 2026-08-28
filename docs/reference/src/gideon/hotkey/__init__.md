# `src/gideon/hotkey/__init__.py`

Docstring only. It exists so the directory ships as a package directory, **not** so the
modules get imported.

These modules run under `/usr/bin/python3` because they need `python3-evdev`, an apt
package that is not part of the vendored runtime. They therefore import **nothing** from
`gideon`, and duplicate what they need (notably the control-socket path) instead.
`gideon.cli.setup` shells out to them. `scripts/build-deb.sh` `chmod 0755`s them so they
stay directly executable after install.
