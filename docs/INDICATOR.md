# The indicator: tray icon, HUD and health panel

An always-on daemon with no window is indistinguishable from a dead one. The indicator is
the visible proof that Gideon is running, holding the microphone, and ready — and when he is
not, it says so within a second or two rather than sitting there looking installed.

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
gideon --ui                      # or: systemctl --user enable --now gideon-ui
gideon --ui --health             # text snapshot, no GUI; exit 1 when offline
```

`gideon --setup` offers all of this.

## The three surfaces

| Surface | Answers |
|---|---|
| **Tray icon** | *Is Gideon alive, and what is he doing right now?* — colour and glyph per state |
| **HUD** | *Did he hear me, and as what?* — a card at the bottom of the screen with the state, your words and Gideon's reply |
| **Health panel** | *Is every part actually working?* — one row per subsystem, from the menu |

## What the HUD shows, and what it does not

One exchange at a time: what you said, and what Gideon answered. It appears only for turns
Gideon is **actually acting on** — after the wake phrase, after the push-to-talk key, or
inside the follow-up window.

Everything else stays off screen. The daemon transcribes every utterance in the room, because
the wake phrase is matched against the transcript rather than by a wake-word model, but
showing those would put every passing conversation on your desktop. A conversation Gideon
ignored leaves no trace on screen; the `----` lines in `journalctl --user -u gideon -f` are
still there if you are debugging why something did not match.

The card is opaque on purpose: the HUD has to be readable over a white page or a photo
wallpaper, and transparency there would cost it its only job.

Pressing the key shows the card **before** you speak, because at that point Gideon is
committed to listening. Saying "hey Gideon" from cold does not — until Whisper has run,
the daemon genuinely does not know the sentence was for it.

## States

| State | Colour | Meaning |
|---|---|---|
| Ready | green | armed, listening for "hey Gideon" or the key |
| Listening | blue | VAD has an open segment — you are being recorded |
| Thinking | amber | transcribing, routing, or waiting on the local model |
| Speaking | violet | Piper is playing; **the microphone is muted** |
| Follow-up | teal | the reply finished; no wake phrase needed for a few seconds |
| Starting | grey | loading models |
| Offline | red, struck through | nothing is listening on the control socket |

Offline is drawn *struck through*, not merely in a different colour, so it stays readable
under a monochrome or symbolic panel theme.

## Menu

* **Service health…** — the panel below.
* **Talk to Gideon** — sends the same `wake` line the push-to-talk key sends: the next thing
  you say is a query, no wake phrase needed.
* **Start / Stop daemon**, **Restart daemon** — `systemctl --user`.
* **Quit indicator** — closes the icon only. The daemon keeps running and keeps listening.

## The health panel

Every row is measured, never assumed. Two sections:

* **Daemon** — mic, VAD, Whisper, Piper, the local brain and the control socket, exactly as
  the daemon reported them into its `StatusBus`. When the daemon is down this section says
  so rather than showing stale ticks.
* **This session** — the three systemd user units and the socket file, checked from the UI
  process, and therefore still meaningful *precisely when the daemon is not answering*.

A local brain shown red is normal if you have not installed Ollama: Gideon falls back to
canned replies, which is a supported configuration. The row exists because "why are the
answers canned" is exactly the question the panel is for.

## How it stays honest

* It subscribes to the daemon's control socket and is **pushed** every state change, so the
  icon moves while you are still speaking.
* The daemon heartbeats every 5 s. Silence past 12 s counts as gone — a unix socket gives no
  timely notice of a peer that died without closing.
* Reconnection backs off to 5 s and **resets on success**, so a crash-restart repaints the
  icon almost immediately.
* It never shares a process with the pipeline: a hung or crashed UI cannot touch the
  microphone. The daemon's side of the feed drops updates rather than blocking.
* One instance only, held by an abstract unix address that cannot be left behind stale.

## Wayland note

GNOME's Mutter implements no layer-shell protocol, so a Wayland-native client cannot place
a window or keep it above others. The HUD needs both, so the process re-execs itself onto
**XWayland** (`GDK_BACKEND=x11`). The tray icon is D-Bus and is unaffected. Run
`gideon --ui --no-x11` to stay on the native backend; the HUD then appears wherever the
compositor decides. `gideon --ui --no-hud` drops the overlay entirely.

## "no control socket after 10s"

`gideon --setup` prints this when the unit is active but nothing answers on the socket. The
daemon is running and still hears you; it just cannot be reached out of band, so the key and
the indicator are both dead. Restart it — `systemctl --user restart gideon` — and re-run the
check. If it recurs, `journalctl --user -u gideon -e | grep control` will show whether the
bind itself failed (a second Gideon, or `ReadWritePaths=%t` missing from the unit).

## Checking it yourself

```bash
gideon --ui --health        # is the daemon up, and is every subsystem healthy?
gideon --ui --self-check    # does the HUD appear for the right turns, and only those?
```

Both exit non-zero on failure, so they work in a script.

## When there is no icon

1. `gideon --ui --health` — if that prints a state, the daemon is fine and only the tray is
   not showing.
2. On GNOME the tray needs an AppIndicator extension; Ubuntu ships and enables one
   (`ubuntu-appindicators`). On plain GNOME install `gnome-shell-extension-appindicator`.
3. `journalctl --user -u gideon-ui -e`.
4. Missing typelib? `gideon --ui` prints the exact apt line and still opens the health panel.
