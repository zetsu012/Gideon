"""Tier 1 clients: Ollama locally, or an OpenAI-compatible cloud provider.

`build()` is the one place that decides which, so `__main__` never has to branch
on the provider name and `nlu/brain.py` never learns there is a choice at all.
"""
from __future__ import annotations
import logging

from . import provider as _provider
from .client import LLM

log = logging.getLogger("gideon.llm")


def build(cfg):
    """Return (client, health_detail, ok) for the configured Tier 1 brain.

    Never raises and never blocks: a misconfigured provider degrades to the local
    model, and a missing local model degrades to canned replies in `brain`.
    """
    local = LLM(cfg.llm_url, cfg.llm_model, cfg.llm_timeout)
    prov = _provider.get(cfg.llm_provider)

    if prov is None:
        if cfg.llm_provider and cfg.llm_provider != _provider.LOCAL:
            log.warning("unknown llm_provider %r; using the local model. Known: %s",
                        cfg.llm_provider, ", ".join(_provider.names()))
        if local.available():
            return local, f"ollama {cfg.llm_model}", True
        return local, f"ollama unreachable at {cfg.llm_url} - canned replies", False

    from ..core import credentials
    from .cloud import CloudLLM
    from .fallback import FallbackLLM

    key = credentials.api_key(prov)
    if not key:
        log.warning("%s is selected but no API key is stored; run: gideon --provider",
                    prov.label)
        if local.available():
            return local, f"{prov.label}: no API key - using ollama {cfg.llm_model}", False
        return local, f"{prov.label}: no API key - canned replies", False
    if not cfg.cloud_model:
        log.warning("%s is selected but cloud_model is empty; run: gideon --provider",
                    prov.label)
        return local, f"{prov.label}: no model chosen - using the local model", False

    # Said every start, not once: this is the line that tells the user their
    # speech is leaving the machine, and it should not be something they can
    # only find by scrolling back to the day they set it up.
    log.info("Tier 1 is %s (%s). Transcribed speech is sent to %s; "
             "the rest of the pipeline stays on this machine.",
             prov.label, cfg.cloud_model, prov.base_url)

    cloud = CloudLLM(prov, cfg.cloud_model, key, cfg.cloud_timeout)
    chained = FallbackLLM(cloud, local)
    if cloud.available():
        return chained, f"{prov.label} {cfg.cloud_model} (cloud)", True
    if local.available():
        return chained, f"{prov.label} unreachable - using ollama {cfg.llm_model}", False
    return chained, f"{prov.label} unreachable, no local model - canned replies", False
