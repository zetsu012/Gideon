"""Try the cloud model, fall back to the local one.

Gideon was offline-first before it could talk to a cloud provider, and choosing a
provider should not throw that away: a dropped wifi connection, an expired key or
an exhausted quota should cost you the better model, not the assistant. So the
configured cloud provider is tried first and Ollama catches what it drops;
`nlu/brain.py` catches what they both drop, with canned replies.

Presents the same three methods as either client, so nothing downstream knows
there is a chain here at all.
"""
from __future__ import annotations
import logging

log = logging.getLogger("gideon.llm")


class FallbackLLM:
    def __init__(self, primary, secondary):
        self.primary, self.secondary = primary, secondary
        self._fell_back = False

    @property
    def label(self) -> str:
        return getattr(self.primary, "label", self.primary.model)

    def available(self, recheck: bool = False) -> bool:
        # Either one being up is enough to call Tier 1 usable.
        return (self.primary.available(recheck) or self.secondary.available(recheck))

    def ask(self, text: str) -> str | None:
        reply = self.primary.ask(text)
        if reply is not None:
            if self._fell_back:
                log.info("%s is answering again", self.label)
                self._fell_back = False
            return reply
        reply = self.secondary.ask(text)
        if reply is not None and not self._fell_back:
            # Worth one line: the answers just changed quality and character, and
            # from the outside that looks like Gideon getting mysteriously worse.
            log.warning("%s did not answer - falling back to the local model %s",
                        self.label, self.secondary.model)
            self._fell_back = True
        return reply

    def reset(self) -> None:
        self.primary.reset()
        self.secondary.reset()
