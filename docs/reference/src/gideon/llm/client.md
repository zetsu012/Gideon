# `src/gideon/llm/client.py`

**Tier 1 brain: a local LLM served by Ollama over HTTP.**

Speaks to `POST /api/chat` and `GET /api/tags` with `urllib` rather than the `ollama` SDK,
so the package gains no dependency for an optional feature.

## The optionality contract

Ollama is optional and its absence must be free and quiet:

- `available()` probes `/api/tags` with a **1.5 s** timeout and **caches the result**, so a
  missing Ollama costs one probe for the process lifetime, not one per utterance.
- The "no local LLM" hint is logged **once** (`_warned`).
- Any request failure logs a warning, sets `_available = None` to force a re-probe next
  turn, and returns `None` — the caller falls back to canned replies.
- **Gideon must never crash or hang because a model is absent.** Every change here is
  measured against that sentence.

If Ollama is running but the configured model is not pulled, that is reported specifically
(`ollama pull …`) rather than as "unavailable".

## Reasoning-model defence

Thinking models burn the whole token budget before answering. Three guards:

1. `"think": False` in the request payload.
2. `done_reason == "length"` → the reply is discarded. A usable spoken answer always
   finishes on its own (`"stop"`); hitting the ceiling means a truncated fragment, and
   speaking half a sentence is worse than the fallback.
3. `_strip_think()` removes `<think>…</think>` blocks that leak into `content` untagged.

When only reasoning came back, a one-time warning names the cause and recommends a
non-reasoning model. See `docs/PLAN.md` for the measured latencies.

## Conversation state

`_history` is a `deque(maxlen=history_turns * 2)` of user/assistant pairs — three turns by
default. `reset()` clears it and is called by `__main__` on a stop word, so a new
conversation does not inherit the last one.

`SYSTEM` constrains replies to at most two short sentences of plain prose: the output is
spoken, so markdown, lists and emoji are actively harmful.

`for_speech()` enforces what `SYSTEM` only requests, and is shared with `llm/cloud.py`.
Local models comply with the instruction; a cloud model is free to ignore it — `gpt-oss`
answers in headings and tables by default — and the reply reaches the speakers before
anyone can see it. Headings, bullets, emphasis, code fences, horizontal rules and link
URLs are stripped; table rows become comma-separated clauses. Plain prose, including
sentences containing hyphens, passes through untouched.

| | |
|---|---|
| Imports | stdlib only (`json`, `logging`, `socket`, `urllib`) |
| Imported by | `__main__` |
| Network | `127.0.0.1:11434` — requires `AF_INET` in the systemd unit's `RestrictAddressFamilies` |
| External dep | **Ollama**, installed by the user (see `docs/DEPENDENCIES.md`) |
