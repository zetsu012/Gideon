"""Wake-phrase matching over transcribed text.

v0.1 detects the wake phrase in the STT transcript rather than with a dedicated
wake-word model. openWakeWord has no pretrained "gideon" model, and training one
is a separate step (see scripts/train_wakeword.py). This approach responds to the
real phrase "hey gideon" out of the box; the cost is that Whisper runs on every
VAD-gated speech segment instead of only after a trigger.
"""
from __future__ import annotations
import difflib, re

_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalise(text: str) -> str:
    return _PUNCT.sub(" ", text.lower()).strip()


def match(text: str, phrases, fuzz: float) -> tuple[bool, str]:
    """Return (matched, remainder). Remainder is whatever followed the wake phrase."""
    norm = normalise(text)
    if not norm:
        return False, ""
    words = norm.split()
    for phrase in phrases:
        p = normalise(phrase)
        n = len(p.split())
        if len(words) < n:
            continue
        head = " ".join(words[:n])
        if head == p or difflib.SequenceMatcher(None, head, p).ratio() >= fuzz:
            return True, " ".join(words[n:]).strip()
    return False, ""
