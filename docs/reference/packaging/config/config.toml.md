# `packaging/config/config.toml`

The shipped defaults, installed to **`/etc/gideon/config.toml`** and listed in
`packaging/debian/conffiles`, so dpkg preserves local edits across upgrades.

Also what `scripts/run-local.sh` points `$GIDEON_CONFIG` at, so a source run and an
installed run read the same values.

Keys map onto the `Config` dataclass — both top-level keys and one level of `[section]`
are flattened onto it, and unknown keys are dropped silently (so a typo is a no-op, not an
error). **The first config file found wins entirely; there is no merging with the
defaults.**

To override per user, copy it to `~/.config/gideon/config.toml` — remembering that the copy
then supplies *all* the values that file sets.

Full key reference: `docs/reference/src/gideon/core/config.md`.
