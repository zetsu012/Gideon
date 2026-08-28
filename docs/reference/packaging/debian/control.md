# `packaging/debian/control`

The package's dpkg metadata. A **template**: `scripts/build-deb.sh` substitutes
`@VERSION@`, `@ARCH@` and `@SIZE@` (measured from the staged tree) on the way into
`DEBIAN/control`.

## `Depends:`

`libc6 (>= 2.35)`, `libstdc++6`, `libgomp1`, `libportaudio2`, `libsndfile1`,
`python3-evdev`, `python3`.

Short list on purpose: the package vendors its own Python, every Python dependency and all
three models, so these are only the C libraries that must be `dlopen()`ed from the system
plus the system python + evdev that the hotkey scripts execute under. See
`requirements/system-apt.txt` and `docs/DEPENDENCIES.md` for what each one is for.

`Recommends:` `pipewire`, `pipewire-pulse`, `wireplumber` — present on a normal desktop and
not worth hard-depending on.

Because the runtime is vendored, the same .deb installs and runs identically on Ubuntu
24.04 (python3.12) and 26.04 (python3.14).

**Keep this file and `requirements/system-apt.txt` in sync.**
