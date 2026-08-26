# `packaging/systemd/gideon.service`

The daemon unit, installed to `/usr/lib/systemd/user/`. It is a **user** unit, not a system
one: the daemon needs the logged-in user's audio devices.

`postinst` runs `systemctl --global enable gideon.service`, so it starts at the next login
for every user.

```bash
systemctl --user restart gideon
journalctl --user -u gideon -f
```

## Ordering and scheduling

`After=pipewire.service sound.target`, `Wants=pipewire.service`. `Restart=on-failure`,
`RestartSec=5`. `Nice=5` + `CPUWeight=50` keep multi-second model loading off the
interactive path.

## Hardening, and the two lines that are not optional

`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp`,
`ProtectKernelTunables`, `ProtectControlGroups`, `MemoryMax=2G`, and `PrivateDevices=false`
(the microphone is a device).

- **`ReadWritePaths=%t`** — `ProtectSystem=strict` makes the whole hierarchy read-only,
  which would stop the push-to-talk control socket from binding. `%t` is `/run/user/UID`,
  the only place the daemon writes. Remove it and push-to-talk silently dies.
- **`RestrictAddressFamilies=… AF_INET AF_INET6`** — the Tier 1 brain reaches Ollama over
  TCP on `127.0.0.1:11434`. Without `AF_INET` every LLM call fails `EAFNOSUPPORT` and Gideon
  falls back to canned replies with no obvious cause.

`IPAddressAllow=localhost` / `IPAddressDeny=any` enforce the offline promise at the kernel
level: Gideon can reach a local model server and nothing else.
