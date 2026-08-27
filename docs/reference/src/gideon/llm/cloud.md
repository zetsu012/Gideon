# `src/gideon/llm/cloud.py`

**Tier 1 over an OpenAI-compatible cloud API.** `CloudLLM` is interface-compatible with
`llm/client.LLM` on purpose — `available()`, `ask()`, `reset()` — so `nlu/brain.py` cannot
tell the two apart and `llm/fallback.py` can chain them.

## No SDK, no dependency

Like the Ollama client, this is `urllib` against a documented JSON endpoint rather than
`openai` or a vendor SDK. That matters more here than usual: every dependency has to be
resolved and vendored into the `.deb` by `scripts/build-deb.sh`, so **cloud support adds
zero Python packages and zero megabytes**.

## What `available()` is really for

It fetches `/models` once and caches the result, which does three jobs: proves the key
works, distinguishes *wrong key* (401/403) from *out of credit* (429) from *no network*
in the log line, and catches a mistyped model id **before** the user asks their first
question. Without that last check a typo surfaces as a generic failure at the worst
possible moment — mid-conversation, out loud.

## The reasoning-model trap, again

`llm/client.py` documents this for local models; it is easier to hit here, because
OpenRouter's catalogue is full of reasoning models. The budget goes on chain-of-thought
and the spoken answer comes back empty or as a truncated fragment — `finish_reason:
"length"`. Both cases return `None` so the fallback speaks instead of half a sentence,
and warn **once** naming the fix. `_strip_think` is shared with the local client.

## `USER_AGENT` is load-bearing, not decoration

Cloudflare fronts `api.cerebras.ai` and rejects urllib's default
`Python-urllib/3.x` with **HTTP 403, body `error code: 1010`** — which is indistinguishable
from a rejected API key and sends debugging straight down the wrong path. Any honest
identifier is accepted; this is not browser spoofing, and removing it silently breaks
Cerebras. `--selftest` asserts the header.

## `MAX_TOKENS` is a ceiling, not a length control

The system prompt asks for two sentences; a compliant model uses well under 100 tokens.
The cap is generous (512) because a reply that trips it is **discarded** — so a tight cap
turns every slightly chatty model into a permanent fallback. At 160 it did exactly that to
reasoning models, which spend the budget before they start answering.

Related: `gpt-oss` reasons by default and is one of only two models on Cerebras' public
catalogue, so requests for that family carry `reasoning_effort: "low"`. Both Cerebras and
OpenRouter accept it. Measured after the change: 0.3–0.5 s per reply, in two clean
sentences.

## Timeout is short on purpose

`DEFAULT_TIMEOUT` is 12 s, well under the local client's 30. This sits between a person
finishing a sentence and Gideon answering aloud: a reply that takes 20 s has already
failed as speech, and waiting for it only delays the fallback the user could have had
immediately.

`list_models()` is separate and **raises** rather than returning empty — it exists for the
interactive wizard, where swallowing the real error would be worse than showing it.

| | |
|---|---|
| Imports | stdlib, `llm/client` (`SYSTEM`, `_strip_think`), `llm/provider` |
| Imported by | `llm/__init__`, `cli/provider` |
| Config | `llm_provider`, `cloud_model`, `cloud_timeout` |
| Key | `core/credentials` |
