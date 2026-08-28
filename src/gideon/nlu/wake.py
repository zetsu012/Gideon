"""Wake-phrase matching over transcribed text.

v0.1 detects the wake phrase in the STT transcript rather than with a dedicated
wake-word model. openWakeWord has no pretrained "gideon" model, and training one
is a separate step (see scripts/train_wakeword.py). This approach responds to the
real phrase "hey gideon" out of the box; the cost is that Whisper runs on every
VAD-gated speech segment instead of only after a trigger.

Matching happens on two levels, and the second is the one that carries the load:

1. Graphemes - difflib over the normalised letters, as before.
2. A consonant skeleton - vowels dropped, consonants folded into Soundex-style
   equivalence classes. Whisper does not mishear "Gideon" as a homophone; it
   mishears it as whatever common English phrase has the same *consonant frame*,
   which is why "get in", "guidion", "giddy on" and "kidin" all reduce to the
   same code as "gideon" (see SKELETON below). One rule therefore covers the
   whole family of mishearings, including ones nobody has hit yet - the old
   hand-grown variant list could only ever cover the ones already observed.

Both levels are scored over a sliding window, because the mishearing usually
does not preserve the word count: "hey gideon" is two words, "hey giddy on" is
three. Comparing only a fixed-length head made the phrase list responsible for
every word-count variant too.

The prefix stays mandatory, and now it is enforced structurally rather than by
the floor: a candidate window must open with a word that resembles the phrase's
own first word. Without that guard the skeleton is too generous - "get in the
car" and "let me get in touch" carry the name's exact consonant frame, and
ordinary speech would wake the daemon constantly.

The known cost of the skeleton is collisions: "hey kitten" reduces to the same
code as "hey gideon". That is accepted deliberately - such an utterance is rare,
it still has to survive speaker verification, and the alternative (a tighter
floor) puts real mishearings like "ok gideon" back out of reach.
"""
from __future__ import annotations
import difflib, re

_PUNCT = re.compile(r"[^a-z0-9 ]+")

# Soundex-style consonant classes. Vowels are dropped entirely: they are what
# the acoustic model gets wrong. 'h' and the semivowels 'w'/'y' are kept as
# their own classes rather than dropped, so the "hey"/"hi" prefix still counts
# for something - without it "kitten" alone would match the full wake phrase.
_CLASS: dict[str, str] = {}
for _chars, _code in (("bfpv", "1"), ("cgjkqsxz", "2"), ("dt", "3"), ("l", "4"),
                      ("mn", "5"), ("r", "6"), ("h", "7"), ("wy", "8")):
    for _ch in _chars:
        _CLASS[_ch] = _code

# How far past the phrase's own length the sliding window may stretch. A
# mishearing splits or merges at most a word or so ("gideon" -> "giddy on").
_SLACK = 1
# How closely the opening word must resemble the phrase's own opening word for a
# window to be considered at all. Deliberately loose - it only has to tell a
# greeting ("hey"/"hi"/"ok"/"a") from a content word ("get", "let", "can").
_PREFIX_FUZZ = 0.5
# Words of transcript the wake phrase may hide in. The phrase is at the head of
# the utterance by construction; this only absorbs a leading filler or two
# ("um, hey gideon...") that the old fixed head window rejected outright.
_LOOKAHEAD = 5


def normalise(text: str) -> str:
    return _PUNCT.sub(" ", text.lower()).strip()


def skeleton(text: str) -> str:
    """Consonant-class frame of a phrase: vowels dropped, runs collapsed."""
    out: list[str] = []
    for ch in text:
        code = _CLASS.get(ch)
        if code and (not out or out[-1] != code):
            out.append(code)
    return "".join(out)


def _prefix_ok(word: str, phrase_word: str) -> bool:
    """Does this window open the way the phrase does?"""
    if word == phrase_word:
        return True
    if skeleton(word) and skeleton(word) == skeleton(phrase_word):
        return True
    return difflib.SequenceMatcher(None, word, phrase_word).ratio() >= _PREFIX_FUZZ


def _score(head: str, phrase: str, phrase_skel: str) -> float:
    """Best of the grapheme and skeleton similarities for one candidate window."""
    if head == phrase:
        return 1.0
    grapheme = difflib.SequenceMatcher(None, head, phrase).ratio()
    head_skel = skeleton(head)
    if not head_skel or not phrase_skel:
        return grapheme
    phonetic = difflib.SequenceMatcher(None, head_skel, phrase_skel).ratio()
    return max(grapheme, phonetic)


def match(text: str, phrases, fuzz: float) -> tuple[bool, str]:
    """Return (matched, remainder). Remainder is whatever followed the wake phrase.

    On a tie the longest matching window wins, so the remainder does not keep a
    stray syllable of the wake phrase and hand it to the brain as the query.
    """
    norm = normalise(text)
    if not norm:
        return False, ""
    words = norm.split()

    best = (0.0, 0)          # (score, words consumed)
    for phrase in phrases:
        p = normalise(phrase)
        if not p:
            continue
        p_words = p.split()
        n = len(p_words)
        p_skel = skeleton(p)
        if not _prefix_ok(words[0], p_words[0]):
            continue
        lo, hi = max(1, n - _SLACK), min(len(words), n + _SLACK, _LOOKAHEAD)
        for size in range(lo, hi + 1):
            head = " ".join(words[:size])
            score = _score(head, p, p_skel)
            if score > best[0] or (score == best[0] and size > best[1]):
                best = (score, size)

    if best[0] >= fuzz:
        return True, " ".join(words[best[1]:]).strip()
    return False, ""
