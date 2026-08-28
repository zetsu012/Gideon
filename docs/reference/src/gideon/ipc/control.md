# `src/gideon/ipc/control.py`

**The daemon's edge to the rest of the desktop: one unix socket, two jobs — arming
push-to-talk, and publishing what Gideon is doing.**

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
| `start()` | binds, `chmod 0600`, listens, serves on a daemon thread. **Never fatal** — returns `False` and logs a warning; a daemon that cannot bind still works, just without push-to-talk and without a tray icon |
| `arm()` | starts the push-to-talk window (also stamped onto the `StatusBus`) |
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


## The protocol

Newline commands in, newline JSON out. No framing, no auth beyond the `0600` file mode —
it is local, per-user, and worth no more complexity than that.

| Command | Reply |
|---|---|
| `wake` | `ok` — arm push-to-talk for `hotkey_window_s` |
| `ping` | `ok` — used to detect a live daemon (see below) |
| `status` | one JSON line: `StatusBus.snapshot()`, then close |
| `subscribe` | a JSON line now, another on **every** change, plus `{"type":"heartbeat"}` every 5 s, until the client goes away |

Client helpers: `send(command)` and `status()`. `gideon/ui/feed.py` re-implements them for
the system python, the same way `hotkey/listener.py` re-implements `default_path()`.

## Push, not poll

A state change has to reach the screen while the user is still speaking, and a UI that woke
up four times a second to ask "anything yet?" would be a battery drain for a daemon that is
idle almost all the time. Hence `subscribe`.

The heartbeat exists so a UI can distinguish **daemon quiet** from **daemon gone**: a unix
socket gives no timely notification of a peer that died without closing.

## A client can never stall the pipeline

Each connection gets its own thread, and each subscriber a bounded queue of
`FEED_QUEUE` (16) lines. `_publish()` runs on the *pipeline's* thread and does exactly one
non-blocking `put` per subscriber; when a queue is full the **oldest** line is dropped, since
a UI wants the newest state and not a backlog. A UI that stops reading loses updates and is
eventually dropped; the main loop never notices.

## Refusing to steal a live socket

A leftover socket file from a killed daemon must be unlinked before `bind()`, but a **live**
daemon leaves an identical-looking file. `start()` therefore sends `ping` first and raises
rather than unlinking if anything answers. Without that check a second daemon — or a stray
`--selftest` — would take the socket away from the instance that owns the microphone: the key
would arm the wrong process, and the tray would faithfully report the state of a daemon that
cannot hear you. `--selftest` additionally binds a scratch path under `/tmp`, never the real one.

**`close()` unlinks only what this instance bound** (`_bound`). The declining instance above
still runs `close()` on its way out, and an unconditional `unlink()` there would delete the
*running* daemon's socket — leaving a perfectly healthy daemon holding an unnamed socket that
the key, the tray and `gideon --setup` can never reach again. The daemon keeps answering the
microphone, so nothing in the log looks wrong; only the socket file is gone. `--selftest`
asserts both halves: the second instance must decline, and must leave the file alone.
