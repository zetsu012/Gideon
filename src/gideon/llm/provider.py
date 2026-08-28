"""The cloud providers Gideon can use for Tier 1, and what differs between them.

Both supported providers speak the OpenAI chat-completions dialect, so there is
exactly one client (`llm/cloud.py`); everything provider-specific lives in the
table below. Adding a third OpenAI-compatible provider should mean adding one
entry here and nothing else.

Using any of these sends your transcribed speech off the machine. That is a real
change to what Gideon is - the rest of the pipeline is local and stays local -
so it is opt-in, never a default, and the daemon says so out loud at startup.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str
    env_var: str          # honoured as an override, for people who prefer env to a file
    signup: str
    # A model that exists, is cheap and is not a reasoning model, offered as the
    # default in `gideon --provider` so the wizard always has a working answer.
    suggested: str
    # OpenRouter serves thousands of models from every vendor; listing them all
    # at a voice prompt is useless, so the wizard filters to this prefix set.
    hint: str = ""


PROVIDERS = {
    "cerebras": Provider(
        key="cerebras",
        label="Cerebras",
        base_url="https://api.cerebras.ai/v1",
        env_var="CEREBRAS_API_KEY",
        signup="https://cloud.cerebras.ai",
        # Verified against the public catalogue: it currently serves gpt-oss-120b
        # and gemma-4-31b only. gemma is the suggestion because gpt-oss is a
        # reasoning model - see the reasoning_effort note in llm/cloud.py.
        suggested="gemma-4-31b",
        hint="fastest option by a wide margin; small catalogue (gemma, gpt-oss)",
    ),
    "openrouter": Provider(
        key="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        env_var="OPENROUTER_API_KEY",
        signup="https://openrouter.ai/keys",
        suggested="meta-llama/llama-3.3-70b-instruct",
        hint="one key for many vendors; includes free models and slow ones",
    ),
}

# "ollama" is not in PROVIDERS: it needs no key, no base URL entry and no
# catalogue call, and it is the default rather than a choice. Code that asks
# "is this a cloud provider" should test `name in PROVIDERS`.
LOCAL = "ollama"


def get(name: str) -> Provider | None:
    return PROVIDERS.get((name or "").strip().lower())


def names() -> tuple[str, ...]:
    return (LOCAL, *PROVIDERS)
