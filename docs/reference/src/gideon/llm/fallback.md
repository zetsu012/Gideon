# `src/gideon/llm/fallback.py`

**Try the cloud model, fall back to the local one.** `FallbackLLM(primary, secondary)`
presents the same three methods as either client, so nothing downstream knows there is a
chain at all.

## Why it exists

Gideon was offline-first before it could talk to a cloud provider, and picking a provider
should not throw that away. A dropped wifi connection, an expired key or an exhausted
quota should cost you the *better model*, not the assistant. So the order is: cloud →
Ollama → canned replies (the last handled by `nlu/brain.py`, which already returns
`_NO_BRAIN` when Tier 1 gives it nothing).

## The one log line that matters

When the primary stops answering, the fallback logs a warning **once** naming both models,
and logs again when the primary recovers. This is not noise: the answers just changed
quality and character, and from outside the process that looks like Gideon mysteriously
getting worse. The state is one bool, so a flapping connection cannot spam the journal.

`available()` is true if *either* is up — Tier 1 is usable if anything can answer.

| | |
|---|---|
| Imports | stdlib only |
| Imported by | `llm/__init__` |
