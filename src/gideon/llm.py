"""Tier 1 brain: a local LLM served by Ollama.

Talks HTTP with urllib rather than the ollama SDK so the package gains no new
dependency. Ollama is entirely optional: if it is not installed or not running,
availability probing fails once, is logged once, and the caller falls back to the
built-in canned replies. Gideon must never crash or hang because a model is absent.
"""
from __future__ import annotations
import json, logging, socket, urllib.error, urllib.request
from collections import deque

log = logging.getLogger("gideon.llm")

SYSTEM = (
    "You are Gideon, a voice assistant. Your reply is spoken aloud, so answer in "
    "at most two short sentences. Use plain prose: no markdown, lists, code blocks, "
    "emoji or symbols. If you do not know something, say so briefly."
)


class LLM:
    def __init__(self, url="http://127.0.0.1:11434", model="llama3.2:3b",
                 timeout=20.0, history_turns=3):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # user/assistant pairs kept for follow-up context
        self._history: deque[dict] = deque(maxlen=history_turns * 2)
        self._available: bool | None = None
        self._warned = False
        self._thinking_warned = False

    # -- plumbing -----------------------------------------------------------
    def _post(self, path: str, payload: dict, timeout: float | None = None) -> dict:
        req = urllib.request.Request(
            self.url + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
            return json.loads(r.read())

    def available(self, recheck: bool = False) -> bool:
        """Cheap probe; result is cached so a missing Ollama costs nothing per turn."""
        if self._available is not None and not recheck:
            return self._available
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=1.5) as r:
                tags = json.loads(r.read())
            names = {m.get("name", "") for m in tags.get("models", [])}
            self._available = True
            if self.model not in names and not any(
                    n.split(":")[0] == self.model.split(":")[0] for n in names):
                log.warning("ollama is running but %r is not pulled; try: ollama pull %s",
                            self.model, self.model)
                self._available = False
        except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
            if not self._warned:
                log.info("no local LLM (%s) - falling back to built-in replies. "
                         "Install: curl -fsSL https://ollama.com/install.sh | sh", type(e).__name__)
                self._warned = True
            self._available = False
        return self._available

    # -- use ----------------------------------------------------------------
    def ask(self, text: str) -> str | None:
        """Return the model's reply, or None if unavailable/failed."""
        if not self.available():
            return None
        messages = [{"role": "system", "content": SYSTEM}, *self._history,
                    {"role": "user", "content": text}]
        try:
            data = self._post("/api/chat", {
                "model": self.model, "messages": messages, "stream": False,
                "think": False,
                "options": {"temperature": 0.6, "num_predict": 160},
            })
        except Exception as e:                      # network, timeout, bad JSON
            log.warning("llm request failed (%s); using fallback", type(e).__name__)
            self._available = None                  # re-probe next time
            return None

        msg = data.get("message") or {}
        reply = _strip_think((msg.get("content") or "").strip())

        # Reasoning models (qwen3, deepseek-r1, ...) spend the whole token budget
        # thinking and return an empty content with done_reason "length" - at CPU
        # speed that is a 15-20 s wait for nothing. Detect it and say so once,
        # rather than silently falling back forever.
        # A usable spoken answer always completes on its own (done_reason "stop").
        # Hitting the token ceiling means either a reasoning model burning the
        # budget on chain-of-thought - which may arrive as `thinking` OR leak
        # straight into `content` untagged - or a model ignoring the two-sentence
        # instruction. Either way the text is a truncated fragment, so speak the
        # fallback instead of half a sentence.
        if data.get("done_reason") == "length":
            reply = ""

        if not reply:
            if msg.get("thinking") or data.get("done_reason") == "length":
                if not self._thinking_warned:
                    log.warning(
                        "%r produced only reasoning and no answer. It is a thinking "
                        "model and is too slow for speech on CPU. Use a non-reasoning "
                        "model instead: ollama pull llama3.2:3b", self.model)
                    self._thinking_warned = True
            return None
        self._history.append({"role": "user", "content": text})
        self._history.append({"role": "assistant", "content": reply})
        return reply

    def reset(self) -> None:
        self._history.clear()


def _strip_think(text: str) -> str:
    """Remove <think>...</think> blocks that reasoning models emit."""
    while "<think>" in text and "</think>" in text:
        a, b = text.index("<think>"), text.index("</think>") + len("</think>")
        text = (text[:a] + text[b:]).strip()
    return text.strip()
