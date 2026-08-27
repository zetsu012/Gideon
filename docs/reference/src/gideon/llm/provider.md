# `src/gideon/llm/provider.py`

**The table of cloud providers, and nothing else.** Both supported providers speak the
OpenAI chat-completions dialect, so there is exactly one client (`llm/cloud.py`) and every
difference between them lives in the `PROVIDERS` dict here: base URL, environment
variable, signup page, a suggested non-reasoning model, and a one-line hint the setup
wizard prints. Adding a third OpenAI-compatible provider should mean adding one entry and
touching nothing else.

## `ollama` is deliberately not in the table

It needs no key, no base-URL entry and no catalogue call, and it is the default rather
than a choice. Code asking "is this a cloud provider" tests `name in PROVIDERS`; `LOCAL`
holds the string `"ollama"` so that test never becomes a literal scattered across files.

## Why this file exists at all

Choosing a cloud provider sends transcribed speech off the machine — a real change to what
Gideon is, since every other stage is local and stays local. Keeping the providers in one
declarative table makes it possible to state that plainly in one place, and makes the
"which of these is local" question answerable by reading rather than by tracing calls.

| | |
|---|---|
| Imports | stdlib only |
| Imported by | `llm/__init__`, `llm/cloud`, `cli/provider`, `core/credentials` (via caller) |
| Providers | `cerebras`, `openrouter` |
