# `src/gideon/ui/feed.py`

**Client half of the daemon's status socket, with reconnection.** Stdlib only, no GTK.

## The interesting part is the unhappy path

The UI's whole job is to be trustworthy about whether Gideon is alive, so:

* **Absence is a state, not an error.** The daemon can be stopped, restarting after a crash,
  or not installed. Each produces `on_offline(reason)` and a retry; nothing raises, nothing
  gives up.
* **Reconnect forever, but politely.** Backoff grows 0.5 s → 5 s so a permanently absent
  daemon costs nothing, and **resets on success**, so a `Restart=on-failure` bounce repaints
  the icon within a second rather than after a minute of exponential backoff.
* **Silence is not health.** The daemon heartbeats every 5 s; a connection quiet for
  `DEAD_AFTER_S` (12 s) is treated as dead even though the unix socket never noticed.
* **One announcement per outage,** not one per retry: the icon goes red immediately and then
  stays quiet.

## Surface

| Name | Notes |
|---|---|
| `socket_path()` | must match `gideon.ipc.control.default_path()` — re-stated, not imported |
| `send(command)` | one-shot `wake` / `ping`; `False` if nothing is listening |
| `StatusFeed(on_status, on_offline)` | `start()` / `stop()`; callbacks arrive on **its own thread** |
| state constants | `IDLE`, `LISTENING`, …, plus `OFFLINE`, which the daemon never sends — it is what *this side* concludes |

Callers are responsible for bouncing callbacks onto the GTK main loop; `tray.py` does it with
`GLib.idle_add`.
