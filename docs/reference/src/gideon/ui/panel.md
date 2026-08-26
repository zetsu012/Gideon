# `src/gideon/ui/panel.py`

**The health panel: every part of Gideon, and whether it is actually working.**

## The design rule

**Nothing in this window is a constant.** Every row is either a fact the daemon published
into its `StatusBus`, or something this process just measured. A row that said
`Microphone: OK` because a list in this file said so would make the whole indicator
worthless — so there is no such list.

## Two sources, kept visibly apart

| Section | Rows | Available when |
|---|---|---|
| **Daemon** | mic, VAD, Whisper, Piper, local brain, control socket, last error | only while the daemon answers — when it does not, the section says so instead of showing stale green ticks |
| **This session** | `gideon.service`, `gideon-ui.service`, `gideon-hotkey.service`, the socket file | always — and therefore still meaningful **precisely when the daemon is not answering** |

A third section shows the last utterance, its kind (`wake` / `follow` / `key` / `ignored`)
and how long ago it was heard.

## Details

* Health keys the daemon reports but `theme.SUBSYSTEMS` does not name are still rendered, so
  a subsystem added to the daemon later shows up here without touching this file.
* A subsystem that has never reported is `○ not reported yet`, never a tick.
* `gideon-ui` and `gideon-hotkey` are optional: `not installed — optional` rather than a red cross.
* The unit checks shell out to `systemctl`, so the 3 s refresh timer **only runs while the
  window is visible** (`show`/`hide` handlers), and closing hides rather than destroys so the
  tray can keep one instance.
