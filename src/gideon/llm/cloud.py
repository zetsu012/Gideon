"""Tier 1 over a cloud provider that speaks OpenAI chat-completions.

Interface-compatible with `llm/client.LLM` on purpose: `available()`, `ask()`,
`reset()`. `nlu/brain.py` cannot tell the two apart, and `llm/fallback.py` can
chain them.

Like the Ollama client this uses urllib rather than an SDK, so cloud support adds
**no Python dependency** - which matters here more than usual, because every
dependency has to be vendored into the .deb.

The rules the local client established still hold and are easy to break:
a provider that is down, rate-limiting, out of credit or simply misconfigured
must degrade to the next tier, never crash and never hang the microphone.
"""
from __future__ import annotations
import json, logging, socket, urllib.error, urllib.request
from collections import deque

from .client import SYSTEM, _strip_think, for_speech

log = logging.getLogger("gideon.llm.cloud")

# Deliberately short. This sits between a person finishing a sentence and Gideon
# answering out loud; a reply that takes 20 s has already failed as speech, and
# waiting for it just delays the canned fallback the user could have had at once.
DEFAULT_TIMEOUT = 12.0

# A ceiling, not a length control - the system prompt asks for two sentences and
# a compliant model uses well under 100 tokens. It is generous because a reply
# that trips the ceiling is DISCARDED (see `finish_reason == "length"` below), so
# a tight cap turns every slightly-chatty model into a permanent fallback. That
# is what 160 did to reasoning models, which spend the budget before the answer.
MAX_TOKENS = 512

# Cloudflare sits in front of api.cerebras.ai and rejects urllib's DEFAULT
# User-Agent ("Python-urllib/3.x") with HTTP 403 "error code: 1010" - which
# reads exactly like a rejected API key and sent a real debugging session down
# the wrong path. Any honest identifier is accepted; this is not spoofing a
# browser, and it must not be removed as cosmetic.
USER_AGENT = "Gideon/0.1 (+https://github.com/gideon-assistant)"


class CloudLLM:
    def __init__(self, provider, model: str, api_key: str,
                 timeout: float = DEFAULT_TIMEOUT, history_turns: int = 3):
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self._key = api_key
        self._history: deque[dict] = deque(maxlen=history_turns * 2)
        self._available: bool | None = None
        self._warned = False
        self._reasoning_warned = False

    @property
    def label(self) -> str:
        return f"{self.provider.label} {self.model}"

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json",
             "Authorization": f"Bearer {self._key}",
             "User-Agent": USER_AGENT}
        if self.provider.key == "openrouter":
            # OpenRouter attributes traffic with these and rate-limits unlabelled
            # anonymous callers harder. They are not required, and carry nothing
            # about the user.
            h["HTTP-Referer"] = "https://github.com/gideon-assistant"
            h["X-Title"] = "Gideon"
        return h

    def _request(self, path: str, payload: dict | None, timeout: float) -> dict:
        req = urllib.request.Request(
            self.provider.base_url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=self._headers(),
            method="POST" if payload is not None else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def available(self, recheck: bool = False) -> bool:
        """Probe the catalogue once. A bad key must be diagnosed, not retried forever."""
        if self._available is not None and not recheck:
            return self._available
        if not self._key:
            if not self._warned:
                log.warning("no API key for %s - run: gideon --provider", self.provider.label)
                self._warned = True
            self._available = False
            return False
        try:
            data = self._request("/models", None, timeout=4.0)
            ids = {m.get("id", "") for m in data.get("data", [])}
            self._available = True
            # A typo in a model name is otherwise invisible until the first
            # question, and shows up as a generic failure at the worst moment.
            if ids and self.model not in ids:
                log.warning("%s does not list %r; requests will probably fail. "
                            "Run: gideon --provider", self.provider.label, self.model)
        except urllib.error.HTTPError as e:
            if not self._warned:
                hint = ("the API key looks wrong or expired" if e.code in (401, 403)
                        else "out of credit or rate limited" if e.code == 429
                        else f"HTTP {e.code}")
                log.warning("%s unreachable (%s) - falling back", self.provider.label, hint)
                self._warned = True
            self._available = False
        except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
            if not self._warned:
                log.info("%s unreachable (%s) - falling back to the local model "
                         "or canned replies", self.provider.label, type(e).__name__)
                self._warned = True
            self._available = False
        return self._available

    def ask(self, text: str) -> str | None:
        if not self.available():
            return None
        messages = [{"role": "system", "content": SYSTEM}, *self._history,
                    {"role": "user", "content": text}]
        try:
            payload = {
                "model": self.model, "messages": messages, "stream": False,
                "temperature": 0.6, "max_tokens": MAX_TOKENS,
            }
            # gpt-oss is the only model on Cerebras' public catalogue besides
            # gemma, and it reasons by default: left alone it spends the token
            # budget thinking and returns a truncated answer or none at all.
            # Both Cerebras and OpenRouter accept this knob for that family.
            if "gpt-oss" in self.model.lower():
                payload["reasoning_effort"] = "low"
            data = self._request("/chat/completions", payload, timeout=self.timeout)
        except Exception as e:                      # network, timeout, HTTP, bad JSON
            log.warning("%s request failed (%s); using fallback",
                        self.provider.label, type(e).__name__)
            self._available = None                  # re-probe next turn
            return None

        choices = data.get("choices") or []
        if not choices:
            # Some providers report a refusal or a content filter this way.
            log.warning("%s returned no choices: %s", self.provider.label,
                        (data.get("error") or {}).get("message", "no detail"))
            return None
        choice = choices[0]
        msg = choice.get("message") or {}
        reply = for_speech(_strip_think((msg.get("content") or "").strip()))

        # Same trap as local reasoning models, and easier to fall into here
        # because OpenRouter's catalogue is full of them: the budget goes on
        # chain-of-thought and the spoken answer is empty or a truncated
        # fragment. Speak the fallback rather than half a sentence.
        if choice.get("finish_reason") == "length":
            reply = ""
        if not reply:
            if msg.get("reasoning") or choice.get("finish_reason") == "length":
                if not self._reasoning_warned:
                    log.warning("%r spent its budget reasoning and returned no answer. "
                                "Pick a non-reasoning model: gideon --provider", self.model)
                    self._reasoning_warned = True
            return None

        self._history.append({"role": "user", "content": text})
        self._history.append({"role": "assistant", "content": reply})
        return reply

    def reset(self) -> None:
        self._history.clear()


def list_models(provider, api_key: str, timeout: float = 10.0) -> list[str]:
    """Fetch the catalogue for the setup wizard. Raises on failure - the wizard
    is interactive and a silent empty list there would be a worse experience
    than the actual error."""
    req = urllib.request.Request(
        provider.base_url + "/models",
        headers={"Authorization": f"Bearer {api_key}",
                 "User-Agent": USER_AGENT},          # see USER_AGENT: Cloudflare
        method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))
