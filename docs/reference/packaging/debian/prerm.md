# `packaging/debian/prerm`

Runs before removal, on `remove|deconfigure`.

`systemctl --global disable gideon.service`, then walks `loginctl list-users` and stops the
unit inside each active user session (`systemctl --user -M "${uid}@" stop`). A `--global`
disable alone would leave already-running instances holding the microphone until logout.

Every command is `|| true`: uninstalling must not fail because systemd is absent or a
session has already gone away.
