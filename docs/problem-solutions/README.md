# Problem / solution notes

One file per real problem that took work to understand, written in plain language.

These are **not** design docs. `docs/ARCHITECTURE.md` says how Gideon works today;
these say *why a piece of it is shaped the way it is* — what broke, what the actual
cause turned out to be, what was tried, and what would break again if someone
"simplified" the fix.

Write one when a fix depends on a non-obvious reason. If the next person could remove
your code because it looks redundant, it belongs here.

| Note | Problem |
|---|---|
| [wake-phrase-mishearing.md](wake-phrase-mishearing.md) | "Hey Gideon" often didn't wake him — Whisper writes the name as "get in", and the matcher compared spellings instead of sounds |
