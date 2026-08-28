# `src/gideon/core/state.py`

**The daemon's bulletin board: what Gideon is doing, and whether each part works.**

## The problem it solves

A daemon with no window is indistinguishable from a dead one. Everything the tray icon,
the HUD and the health panel display comes from here — so this module is the single
source of truth for "is Gideon at your service", and the UI is a pure view of it.

It is pure data: nothing in it imports audio, models or GTK.

## Two kinds of fact

| | What it is | Written by |
|---|---|---|
| **state** | where the pipeline is *right now* — `starting`, `idle`, `listening`, `thinking`, `speaking`, `followup`, `stopped` | `__main__.py` at each transition |
| **health** | one entry per subsystem (`mic`, `vad`, `stt`, `tts`, `llm`, `control`), each `{ok, detail, at}` | at load time, and again whenever something fails |

The health dict is why the panel can never lie: a row is rendered from whatever the daemon
actually reported, and a subsystem that never reported shows as *unknown*, not as fine.

## The rule that shapes the design

**The pipeline is single-threaded and nothing here may block it.** So writers take a short
lock, stamp a field, and fan out through *non-blocking* callbacks. A subscriber that cannot
keep up loses updates; it never slows the microphone down. `_emit_locked()` swallows every
exception a subscriber raises for the same reason.

## `StatusBus`

| Method | Notes |
|---|---|
| `start()` | starts the expiry ticker (see below) |
| `set_state(state)` | no-op if unchanged, so repeated stamps cost nothing |
| `heard(text, kind)` | `kind` is `wake` / `key` / `follow` / `ignored` — the UI shows ignored utterances differently |
| `spoke(reply)` | the last thing said out loud |
| `windows(follow_until=…, armed_until=…)` | publishes the two deadlines |
| `health_set(name, ok, detail)` | logs on the transition into a bad state, not on every call |
| `snapshot()` | the dict that crosses the socket as JSON |
| `subscribe(cb)` / `unsubscribe(cb)` | `cb(snapshot)` must not block and must not raise |

## Why there is a thread

The follow-up and push-to-talk windows end **by the clock running out**, not by anything the
pipeline does — and at that moment the pipeline is blocked reading the microphone, so it
cannot announce the change itself. One 4 Hz ticker watches the two deadlines and publishes
their expiry. Without it a UI would show "listening for a follow-up" forever.

## Ordering trap

`__main__.py` publishes the follow-up deadline **before** setting the state to `followup`.
Reversed, the ticker can observe `FOLLOWUP` alongside a stale (already expired) deadline and
snap it straight back to `idle`.
