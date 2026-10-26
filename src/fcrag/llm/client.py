"""LLM access through LiteLLM: one interface for hosted APIs and local models (Ollama, vLLM)."""

import logging
from collections.abc import Iterator
from typing import Any, Protocol

from fcrag.config import Settings

log = logging.getLogger(__name__)

Message = dict[str, str]


class LLM(Protocol):
    model: str
    """The model that produced the last answer (the primary one until a fallback is used)."""

    def stream(self, messages: list[Message]) -> Iterator[str]: ...


class LiteLLMClient:
    """Streams completions from the main model, then each fallback in turn.

    Fallback is handled here rather than by LiteLLM: its ``fallbacks`` option breaks synchronous
    streaming. A model is only skipped if it fails before its first token; a failure mid-answer
    is raised, so two models' output are never spliced together.
    """

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
            started = False
            try:
                response: Any = litellm.completion(
                    model=model,
                    messages=messages,
                    stream=True,
                    temperature=0,
                    timeout=self._timeout,
                    num_retries=1,
                )
                for part in response:
                    delta = part.choices[0].delta.content if part.choices else None
                    if delta:
                        if not started:
                            started, self.model = True, model
                        yield delta
                if started:
                    return
                raise RuntimeError(f"{model} returned an empty answer")
            except Exception as exc:
                if started:
                    raise
                log.warning("LLM %s failed, trying the next model: %s", model, exc)
                last_error = exc
        raise RuntimeError(f"all LLMs failed; last error: {last_error}") from last_error
