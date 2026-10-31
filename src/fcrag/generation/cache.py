"""Response cache: the same question, asked the same way, against the same index, is answered
once and replayed afterwards.

The key covers everything that changes an answer: the normalised question, the filters and access
groups, the prompt version, the model and an index version read from the document registry, so
any ingestion or re-ingestion starts fresh. Follow-up questions (with history) are never cached,
since their meaning depends on the conversation. If Redis is unreachable the cache steps aside:
answers are computed as without it.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Protocol

from sqlalchemy import Engine, func, select

from fcrag.retrieval.search import Filters

log = logging.getLogger(__name__)

PREFIX = "fcrag:answer:"


def normalise(question: str) -> str:
    """Case, spacing and trailing punctuation do not change the question."""
    return " ".join(question.lower().split()).rstrip("?!.。 ")


class ResponseCache(Protocol):
    def key(self, question: str, filters: Filters, prompt_version: str, model: str) -> str | None:
        """None when no key can be built (the index version is unknown): do not cache."""
        ...

    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, result: dict[str, Any]) -> None: ...


class RedisResponseCache:
    def __init__(self, redis: Any, ttl_s: int, index_version: Callable[[], str]) -> None:
        self.redis, self.ttl_s, self.index_version = redis, ttl_s, index_version
        self._warned = False

    def _warn(self, action: str, exc: Exception) -> None:
        if not self._warned:  # once: an unreachable Redis would otherwise log every request
            log.warning("response cache %s failed, answering without it: %s", action, exc)
            self._warned = True

    def key(self, question: str, filters: Filters, prompt_version: str, model: str) -> str | None:
        try:
            version = self.index_version()
        except Exception as exc:
            self._warn("index version", exc)
            return None
        payload = json.dumps(
            [normalise(question), asdict(filters), prompt_version, model, version], sort_keys=True
        )
        return PREFIX + hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        try:
            raw = self.redis.get(key)
        except Exception as exc:
            self._warn("read", exc)
            return None
        return dict(json.loads(raw)) if raw else None

    def set(self, key: str, result: dict[str, Any]) -> None:
        try:
            self.redis.setex(key, self.ttl_s, json.dumps(result, ensure_ascii=False, default=str))
        except Exception as exc:
            self._warn("write", exc)


def registry_version(engine: Engine) -> str:
    """Changes whenever a document is added, re-ingested or changes status."""
    from fcrag.db.models import Document
    from fcrag.db.session import session_scope

    with session_scope(engine) as session:
        count, latest = session.execute(select(func.count(), func.max(Document.updated_at))).one()
    return f"{count}:{latest}"
