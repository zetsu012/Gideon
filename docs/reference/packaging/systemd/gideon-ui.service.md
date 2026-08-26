# `packaging/systemd/gideon-ui.service`

**Systemd *user* unit for the tray indicator.** Installed to
`/usr/lib/systemd/user/gideon-ui.service`, enabled for every user by `postinst`.

```ini
PartOf=graphical-session.target
After=graphical-session.target
WantedBy=graphical-session.target
ExecStart=/usr/bin/gideon --ui
Restart=on-failure
```

## The decisions

* **Bound to the graphical session, not to `gideon.service`.** The indicator deliberately
  starts even when the daemon is dead, because *"Gideon is not running"* is exactly the
  thing it exists to tell you. Making it `Requires=gideon.service` would hide the failure it
  is meant to report.
* **No `BindsTo`, no `After=gideon.service`.** It reconnects to the control socket on its
  own (`ui/feed.py`), so a daemon restart must not take the icon down with it.
* **Enabling it on a headless machine costs nothing** — `graphical-session.target` never
  activates there, so it simply never starts.
* **None of the daemon's sandboxing.** It is a desktop client: it needs the session bus, the
  display and `systemctl --user`, all of which `ProtectSystem=strict` and friends would break.
