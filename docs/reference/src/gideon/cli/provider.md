# `src/gideon/cli/provider.py`

**`gideon --provider`: choose where Tier 1 answers come from.** Pick a provider, paste a
key, choose a model from the provider's live catalogue, ask it a test question, then the
key is written to `~/.config/gideon/credentials.toml` (0600) and the choice to the user
config.

## Writing the user config can silently shadow `/etc`

`Config.load()` takes the **first file that exists and does not merge**. So creating
`~/.config/gideon/config.toml` containing only the provider keys would revert every other
setting in `/etc/gideon/config.toml` — voice, wake phrases, thresholds — to its built-in
default, invisibly. `_write_config()` therefore **seeds the user file as a copy of the
system one** when it does not yet exist. `--selftest` asserts this by seeding a system
config with distinctive values and checking they survive the round trip.

## The settings go in their own marked block

Rather than editing the existing `[llm]` section, the wizard appends a block between
`# >>> gideon --provider >>>` markers and rewrites it wholesale on each run. Section names
are irrelevant to `Config.load()` (it flattens one level of *any* section) and later keys
win, so a self-contained block at the end of the file is both idempotent to rewrite and
impossible to half-apply. The selftest asserts a re-run replaces the block instead of
stacking copies.

## It opens the firewall, and closes it again

`gideon.service` sets `IPAddressAllow=localhost` / `IPAddressDeny=any`, because Gideon was
built to be offline. Whether systemd **enforces** that for a *user* unit depends on BPF
cgroup delegation, so a cloud provider works on some machines and fails as "unreachable"
on others — the same symptom as a bad key. Choosing a cloud provider therefore writes
`~/.config/systemd/user/gideon.service.d/10-cloud-provider.conf` (which resets
`IPAddressDeny` and allows outbound), and choosing Ollama deletes it. Failure to write it
is a warning, never fatal: the settings are already saved and the drop-in only matters
where the filter is enforced.

## The catalogue, filtered

OpenRouter lists 400+ models and most are useless for speech, so the wizard shows a
shortlist matched against `SUGGEST_HINTS` and accepts a number, a search term, or an exact
id. A failed catalogue fetch is **not fatal** — the user may know exactly which model they
want — so it degrades to a free-text prompt.

The test question is the last step before saving, and a slow answer is called out: over
4 s is usable as an API and bad as speech.

| | |
|---|---|
| Imports | `core/config`, `core/credentials`, `llm/provider`, `llm/cloud` |
| Imported by | `__main__` (lazily, only for `--provider`) |
| Writes | `~/.config/gideon/config.toml`, `~/.config/gideon/credentials.toml` |
