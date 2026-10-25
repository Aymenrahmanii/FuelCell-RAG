"""LLM access through LiteLLM: one interface for hosted APIs and local models (Ollama, vLLM)."""

from collections.abc import Iterator
from typing import Any, Protocol

from fcrag.config import Settings

Message = dict[str, str]


class LLM(Protocol):
    model: str

    def stream(self, messages: list[Message]) -> Iterator[str]: ...


class LiteLLMClient:
    """Streams completions; on failure LiteLLM falls back to the local model (unless restricted)."""

    def __init__(self, settings: Settings) -> None:
        self.model = settings.active_llm_model
        self._fallbacks = [] if settings.restricted_mode else [settings.local_llm_model]
        self._timeout = settings.llm_timeout_s

    def stream(self, messages: list[Message]) -> Iterator[str]:
        import litellm

        response: Any = litellm.completion(
            model=self.model,
            messages=messages,
            stream=True,
            temperature=0,
            timeout=self._timeout,
            num_retries=2,
            fallbacks=self._fallbacks or None,
        )
        for part in response:
            delta = part.choices[0].delta.content
            if delta:
                yield delta
