"""Tracing with self-hosted Langfuse. Without keys configured, every call is a no-op.

Observations are created with explicit parents rather than an implicit "current span": the API
streams answers from a generator that Starlette advances on worker threads, where context-local
state does not survive between tokens.
"""

import logging
from functools import lru_cache
from typing import Any

from fcrag.config import get_settings

log = logging.getLogger(__name__)


class _NoOp:
    """Stands in for a Langfuse observation when tracing is off."""

    trace_id: str | None = None
    id: str | None = None

    def start_observation(self, **_: Any) -> "_NoOp":
        return self

    def update(self, **_: Any) -> "_NoOp":
        return self

    def end(self, **_: Any) -> "_NoOp":
        return self


NOOP = _NoOp()


@lru_cache(maxsize=1)
def client() -> Any | None:
    s = get_settings()
    secret = s.langfuse_secret_key.get_secret_value() if s.langfuse_secret_key else ""
    if not s.langfuse_public_key or not secret:  # an empty line in .env means "off"
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=secret,
            host=s.langfuse_host,
            environment=s.env,
        )
    except Exception:  # tracing must never take the service down
        log.exception("Langfuse unavailable, tracing disabled")
        return None


def start_trace(name: str, **kwargs: Any) -> Any:
    """Root observation of one request; children via ``.start_observation(...)``."""
    c = client()
    return c.start_observation(name=name, **kwargs) if c else NOOP


def score(trace_id: str, name: str, value: float, comment: str | None = None) -> None:
    c = client()
    if c and trace_id:
        c.create_score(trace_id=trace_id, name=name, value=value, comment=comment)


def flush() -> None:
    c = client()
    if c:
        c.flush()
