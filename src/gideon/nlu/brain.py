"""Router. Tier 0 rules answer instantly; Tier 1 hands off to a local LLM.

Shaped after docs/PLAN.md. Tier 0 exists because most of what gets said to a voice
assistant is a pattern, not a reasoning problem, and a 4B model on a laptop CPU
costs 1-2 s that a greeting does not need to spend. Tier 2 (Claude Code) is not
wired yet; the branch below is where it goes.
"""
from __future__ import annotations
import logging, random

log = logging.getLogger("gideon.brain")

_GREET_BACK = ["Hi.", "Hello.", "Hey there.", "Hi, I'm listening."]
_ACK = ["Yes?", "I'm here.", "Go ahead."]
_GREETINGS = ("hi", "hello", "hey", "good morning", "good evening", "good afternoon")
# Said when there is no LLM and no rule matches - honest about the limitation.
# Deliberately does not name Ollama: Tier 1 may be a cloud provider that is
# rate-limited or offline, and telling that user to install Ollama sends them
# to fix the wrong thing. The logs and `gideon --ui --health` say which it is.
_NO_BRAIN = ("I heard you, but I can only say hello right now. "
             "My language model is not reachable.")


class Brain:
    def __init__(self, llm=None):
        self.llm = llm

    def respond(self, text: str, *, awaiting_followup: bool = False) -> str:
        """text is the utterance after the wake phrase ('' if only the wake word)."""
        t = text.strip().lower()

        # Tier 0 - deterministic, no model touched.
        if not t:
            return random.choice(_ACK)
        if t in _GREETINGS or (len(t.split()) <= 3 and t.split()[0] in _GREETINGS):
            return random.choice(_GREET_BACK)

        # Tier 1 - local LLM.
        if self.llm is not None:
            reply = self.llm.ask(text)
            if reply:
                return reply

        # Tier 2 - Claude Code headless would go here.

        if t.startswith("how are you"):
            return "I'm running fine, thanks."
        return _NO_BRAIN


# Backwards-compatible helper used by the offline tests.
def respond(text: str) -> str:
    return Brain().respond(text)
