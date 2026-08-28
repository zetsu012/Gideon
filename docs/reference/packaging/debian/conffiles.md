# `packaging/debian/conffiles`

One line: `/etc/gideon/config.toml`.

Marks that path as a dpkg **conffile**, which is what makes a user's local edits survive an
upgrade — dpkg prompts on a conflict instead of silently overwriting. Any future file under
`/etc/gideon/` that a user is expected to edit must be added here too.
