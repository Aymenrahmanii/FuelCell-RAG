"""LLM access through LiteLLM: one interface for hosted APIs and local models (Ollama, vLLM)."""

import logging
import time
from collections.abc import Iterator
from typing import Any, Protocol

from fcrag import metrics
from fcrag.config import Settings

log = logging.getLogger(__name__)

Message = dict[str, str]

RETRY_STATUS = {429, 500, 502, 503, 504}
"""Rate limits and overloads: worth waiting for before trying the next model."""


class LLM(Protocol):
    model: str
    """The model that produced the last answer (the primary one until a fallback is used)."""

    def stream(self, messages: list[Message]) -> Iterator[str]: ...


class LiteLLMClient:
    """Streams completions from the main model, then each fallback in turn.

    Fallback is handled here rather than by LiteLLM: its ``fallbacks`` option breaks synchronous
    streaming. A model is only skipped if it fails before its first token; a failure mid-answer
    is raised, so two models' output are never spliced together.

    Retries are done here too: LiteLLM's ``num_retries`` needs ``tenacity``, which is not a
    dependency, and without it every rate-limited call fell through to the fallback model.
    """

    retry_delays_s: tuple[float, ...] = (5.0, 15.0)
    """Waits before retrying the same model after a rate limit or overload."""

    def __init__(self, settings: Settings) -> None:
        self.primary = settings.active_llm_model
        self.model = self.primary
        # Restricted mode never falls back to a hosted model: no document text leaves the machine.
        self._fallbacks = [] if settings.restricted_mode else list(settings.llm_fallbacks)
        self._timeout = settings.llm_timeout_s

    def stream(self, messages: list[Message]) -> Iterator[str]:
        import litellm

        last_error: Exception | None = None
        for model in [self.primary, *self._fallbacks]:
            for attempt in range(len(self.retry_delays_s) + 1):
                started = False
                try:
                    response: Any = litellm.completion(
                        model=model,
                        messages=messages,
                        stream=True,
                        temperature=0,
                        timeout=self._timeout,
                    )
                    for part in response:
                        delta = part.choices[0].delta.content if part.choices else None
                        if delta:
                            if not started:
                                started, self.model = True, model
                            yield delta
                    if started:
                        metrics.LLM_CALLS.inc(model=model, outcome="ok")
                        return
                    raise RuntimeError(f"{model} returned an empty answer")
                except Exception as exc:
                    if started:
                        metrics.LLM_CALLS.inc(model=model, outcome="failed")
                        raise
                    last_error = exc
                    retryable = getattr(exc, "status_code", None) in RETRY_STATUS
                    if retryable and attempt < len(self.retry_delays_s):
                        delay = self.retry_delays_s[attempt]
                        metrics.LLM_CALLS.inc(model=model, outcome="retry")
                        log.warning("LLM %s busy (%s), retrying in %.0f s", model, exc, delay)
                        time.sleep(delay)
                        continue
                    metrics.LLM_CALLS.inc(model=model, outcome="fallback")
                    log.warning("LLM %s failed, trying the next model: %s", model, exc)
                    break
        raise RuntimeError(f"all LLMs failed; last error: {last_error}") from last_error
