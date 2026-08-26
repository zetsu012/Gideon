# Setting Gideon up on a new system

Everything ships in the `.deb` — the runtime, the models, and the push-to-talk
key setup. There is nothing to clone and no script to copy.

```bash
sudo apt install ./gideon_0.1.0_amd64.deb
gideon --setup
```

That is the whole procedure. The rest of this page is what those two commands
do and what to check if one of them complains.

---

## `sudo apt install ./gideon_0.1.0_amd64.deb`

Pulls in `libportaudio2`, `libsndfile1`, `libgomp1` and `python3-evdev` from
apt. Nothing else is fetched: the vendored Python, every Python dependency and
all three models are inside the package, so first run works with no network.

## `gideon --setup`

| step | what it does | needs sudo |
| --- | --- | --- |
| 1 | verifies the three models are present | no |
| 2 | verifies PortAudio can enumerate devices | no |
| 3 | enables and starts `gideon.service`, then waits for its control socket to answer | no |
| 4 | offers to wire up a keyboard key; declining leaves you with the wake phrase | — |
| 5 | (if accepted) everything under `gideon --setup-key` below | yes |

After step 3 Gideon is live: say **"hey gideon"** and it answers. It holds the
microphone permanently and ignores everything that is not the wake phrase.

## `gideon --setup-key`

Optional, and re-runnable any time to rebind the key or switch keyboards.

| step | what it does | needs sudo |
| --- | --- | --- |
| 1 | `apt install python3-evdev` if missing — the listener runs on the system python | yes |
| 2 | `usermod -aG input $USER` — read `/dev/input/event*` without root | yes |
| 3 | installs a udev rule for `/dev/uinput` — lets the grabbed keyboard keep typing | yes |
| 4 | lists connected keyboards; you pick one | no |
| 5 | you press the key; it is recorded to `~/.config/gideon/hotkey-key` | no |
| 6 | writes and enables `~/.config/systemd/user/gideon-hotkey.service` | no |

**A press does not start a second Gideon.** It sends `wake` to the running
daemon's control socket, and the daemon treats your next sentence as a query
without the wake phrase. Both routes stay available: key *and* "hey gideon".

If step 2 had to add you to the `input` group, **log out and back in once**.
Group membership is fixed at login, so until you do, neither your shell nor the
systemd user manager can open `/dev/input/event*`. Setup enables the service
without starting it in that case and tells you.

## Checking it worked

```bash
systemctl --user status gideon gideon-hotkey
journalctl --user -u gideon -f            # WAKE / KEY / FOLLOW / ---- per utterance
```

Press the key and speak: the daemon logs `KEY  push-to-talk armed`, then your
sentence, then answers. Also confirm the laptop's own volume keys still work
(the grab is per-device) and that the external keyboard still types (that is
the uinput forwarding).

## If something is wrong

| symptom | cause | fix |
| --- | --- | --- |
| `--setup` reports a missing model | broken package | reinstall the `.deb` |
| `PortAudio not usable` | missing library or no audio session | `sudo apt install libportaudio2`; run in a graphical session |
| `gideon.service is not installed` | running from a source checkout, not the `.deb` | start it with `./scripts/run-local.sh` |
| `not in the 'input' group` | session predates the `usermod` | log out and back in |
| whole keyboard stops typing | `/dev/uinput` not writable | re-run `gideon --setup-key` |
| `no daemon on ...` in the hotkey log | `gideon.service` not running, so presses are slow one-shots | `systemctl --user enable --now gideon` |
| key arms but nothing is answered | nothing said within 10 s | speak right after the press, or raise `hotkey_window_s` in `/etc/gideon/config.toml` |

Deeper detail: `docs/HOTKEY.md` (how the key and the wake phrase share one
daemon) and `docs/ARCHITECTURE.md`.
