# `src/gideon/nlu/brain.py`

**The router.** Decides *how* an utterance gets answered, not what the answer is.

`Brain(llm=None).respond(text, awaiting_followup=False) -> str`. `text` is the utterance
**after** the wake phrase — empty when only the wake word was said.

## Tiers

| Tier | Handles | Cost |
|---|---|---|
| **0** — rules | empty text → an ack (`"Yes?"`); greetings → a greeting back | none |
| **1** — local LLM | anything else, if an `LLM` was passed and answers | ~0.5–2 s |
| **2** — Claude Code headless | *not wired.* The branch is marked in the file | — |
| fallback | `how are you`, then `_NO_BRAIN` | none |

Tier 0 exists because most of what is said to a voice assistant is a pattern, not a
reasoning problem, and a model on a laptop CPU costs seconds a greeting should not spend.

`_NO_BRAIN` is deliberately honest — it names the limitation and tells the user to install
Ollama, rather than pretending to have understood.

`Brain(None)` must never raise; `--selftest` asserts exactly that, because a missing Ollama
is a supported configuration, not an error.

The module-level `respond(text)` helper is a backwards-compatible shim for offline checks.

| | |
|---|---|
| Imports | stdlib `logging`, `random` |
| Imported by | `__main__` |
| See also | `docs/PLAN.md` for the tier rationale |
