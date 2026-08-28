# `packaging/debian/postinst`

Runs after unpacking, on `configure`.

1. **Sanity-checks the vendored runtime** (`/opt/gideon/python/bin/python3 -c 'import sys'`)
   and fails the install if it cannot execute — better to discover a broken or mis-copied
   interpreter here than at first run.
2. `systemctl --global enable gideon.service`, so it is enabled for **every** user session.
   A user unit, because the daemon needs the user's audio devices.
3. Prints the four commands that matter: `gideon --setup` (start here), `--selftest`,
   `--say`, and the `journalctl` line, plus `--setup-key` for push-to-talk.

Exits `0` unconditionally at the end; a failed `systemctl` must not fail the install.
