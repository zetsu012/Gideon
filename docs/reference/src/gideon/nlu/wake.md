# `src/gideon/nlu/wake.py`

**Wake detection — by matching text, not by a wake-word model.**

```python
match(text, phrases, fuzz) -> (matched: bool, remainder: str)
```

`normalise()` lowercases and strips everything outside `[a-z0-9 ]`. `match()` takes the
first *n* words of the transcript (where *n* is the phrase's word count) and accepts on an
exact match or a `difflib.SequenceMatcher` ratio ≥ `fuzz` (default 0.80). The **remainder**
— everything after the phrase — is what gets routed to the brain, so "hey gideon what time
is it" yields `(True, "what time is it")` in one utterance.

## Why this instead of openWakeWord

openWakeWord ships no pretrained "gideon" model and training one is a separate project.
Transcript matching responds to the real phrase on day one. The trade is that Whisper runs
on every speech segment rather than only after a trigger.

## Why the phrase list looks wrong

Whisper renders "Gideon" as **"get in"** at every model size. `hey get in`, `hey guidion`,
`hey giddy on`, `hike it in` and friends in `Config.wake_phrases` are the actual observed
mishearings — they are load-bearing, and a larger Whisper model does not remove the need
for them. Matching only the head of the transcript, plus the mandatory `hey`/`hi` prefix,
is what keeps "get in" from firing on ordinary conversation.

| | |
|---|---|
| Imports | stdlib `difflib`, `re` |
| Imported by | `__main__` (and asserted in `--selftest`) |
| Note | the module docstring mentions `scripts/train_wakeword.py`; that script is future work and does not exist yet |
