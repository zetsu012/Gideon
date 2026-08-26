"""Keyboard push-to-talk trigger.

These modules are NOT imported by the daemon. They run under the system python
(`/usr/bin/python3`) because they need python3-evdev, which is not part of the
vendored runtime - so they deliberately import nothing from the gideon package.
`gideon.setup` shells out to them; see `gideon --setup-key`.
"""
