"""LLM client: retries on rate limits, falls back on other errors, never splices answers."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from fcrag.config import Settings
from fcrag.llm.client import LiteLLMClient


class BusyError(Exception):
    status_code = 429


def _chunks(*texts: str) -> Iterator[Any]:
    for text in texts:
        delta = SimpleNamespace(content=text)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _client(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[Any]
) -> tuple[LiteLLMClient, list[str]]:
    """``outcomes`` per call: an exception to raise, or the chunks to stream."""
    import litellm

    calls: list[str] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs["model"])
        assert "num_retries" not in kwargs  # LiteLLM's retries need tenacity
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr("fcrag.llm.client.time.sleep", lambda s: None)
    settings = Settings(_env_file=None, llm_model="main", llm_fallbacks=["backup"])
    return LiteLLMClient(settings), calls


def test_rate_limit_retries_the_same_model(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client(monkeypatch, [BusyError("429"), _chunks("90 ", "°C")])
    assert "".join(client.stream([])) == "90 °C"
    assert calls == ["main", "main"] and client.model == "main"


def test_other_errors_fall_back_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client(monkeypatch, [ValueError("bad key"), _chunks("ok")])
    assert "".join(client.stream([])) == "ok"
    assert calls == ["main", "backup"] and client.model == "backup"


def test_persistent_rate_limit_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client(monkeypatch, [BusyError("429")] * 3 + [_chunks("ok")])
    assert "".join(client.stream([])) == "ok"
    assert calls == ["main"] * 3 + ["backup"]


def test_failure_mid_answer_is_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Iterator[Any]:
        yield from _chunks("90 ")
        raise BusyError("429")

    client, calls = _client(monkeypatch, [broken()])
    with pytest.raises(BusyError):
        list(client.stream([]))
    assert calls == ["main"]
