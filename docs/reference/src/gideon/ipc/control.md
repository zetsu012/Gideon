# `src/gideon/ipc/control.py`

**The unix socket that lets an outside process arm the running daemon.**

## The problem it solves

A push-to-talk key cannot announce itself through the microphone, and it **must not start
a second Gideon** — the daemon already owns the mic and two pipelines cannot share it. So
the key press travels out of band: the daemon listens on a socket, and a `wake` line is
treated exactly as if the wake phrase had just been heard.

## Socket path

`default_path()`, in order: `$GIDEON_SOCKET`, `$XDG_RUNTIME_DIR/gideon.sock`, or
`/tmp/gideon-$UID/gideon.sock` for sessions without a runtime dir (a bare ssh login).
`$XDG_RUNTIME_DIR` is per-user and tmpfs-backed, so a stale socket cannot survive a reboot.

**`gideon/hotkey/listener.py` re-implements this function rather than importing it** — it
runs on the system python and cannot import the vendored package. The two must be kept in
step by hand.

## `Control`

| Method | Notes |
|---|---|
| `start()` | binds, `chmod 0600`, listens, serves on a daemon thread. **Never fatal** — returns `False` and logs a warning; a daemon that cannot bind still works, just without push-to-talk |
| `consume()` | `True` once per press. Reads and clears the arm under a lock |
| `close()` | stops the thread and unlinks the socket |

A leftover socket file from a killed daemon is unlinked before `bind()`, which would
otherwise fail `EADDRINUSE` with nobody listening. `settimeout(0.5)` on the accept loop is
what makes `close()` prompt.

The arm **expires** after `window_s` (`hotkey_window_s`, 10 s — longer than the follow-up
window because the press comes *before* the sentence). Pressing the key and walking away
must not turn an unrelated sentence an hour later into a query.

## Protocol

Newline commands, no framing, no auth beyond the `0600` file mode — it is local, per-user
and carries one bit. `wake` → `ok`, `ping` → `ok`, anything else → `err`.

`send(command="wake")` is the client half, used by the hotkey listener and by `--selftest`,
which does a full bind → send → consume round trip.

| | |
|---|---|
| Imports | stdlib only |
| Imported by | `__main__`, `cli.setup` |
| Requires | `ReadWritePaths=%t` in `gideon.service` — `ProtectSystem=strict` otherwise blocks the bind |
