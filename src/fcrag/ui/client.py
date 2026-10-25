"""Thin HTTP client for the API. The UI never talks to Qdrant or Postgres directly."""

import json
from collections.abc import Iterator
from typing import Any

import httpx

from fcrag.config import get_settings


def _headers() -> dict[str, str]:
    key = get_settings().api_key
    return {"X-API-Key": key.get_secret_value()} if key else {}


def _url(path: str) -> str:
    return get_settings().api_url.rstrip("/") + path


def health() -> dict[str, Any]:
    try:
        response = httpx.get(_url("/health"), headers=_headers(), timeout=5)
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result
    except httpx.HTTPError as exc:
        return {"status": "down", "error": str(exc)}


def ask_stream(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield the API's server-sent events as dicts."""
    with httpx.stream(
        "POST", _url("/ask/stream"), json=payload, headers=_headers(), timeout=180
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield json.loads(line[6:])


def documents() -> list[dict[str, Any]]:
    response = httpx.get(_url("/documents"), headers=_headers(), timeout=30)
    response.raise_for_status()
    rows: list[dict[str, Any]] = response.json()
    return rows


def page_image(doc_id: str, version: int, page: int) -> bytes | None:
    response = httpx.get(
        _url(f"/documents/{doc_id}/v{version}/pages/{page}.png"), headers=_headers(), timeout=30
    )
    return response.content if response.status_code == 200 else None


def send_feedback(payload: dict[str, Any]) -> bool:
    response = httpx.post(_url("/feedback"), json=payload, headers=_headers(), timeout=10)
    return response.status_code == 201
