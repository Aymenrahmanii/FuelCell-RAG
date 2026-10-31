"""Audit log: every answered question with its user, groups, sources and answer.

Rows are kept for ``audit_retention_days`` (0 turns the log off) and removed by
``fcrag audit-prune``, run daily (cron, a Kubernetes CronJob, ...). Writing is best effort: an
unreachable database is logged and never fails the answer the user is waiting for.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, delete

from fcrag.db.models import AuditRecord
from fcrag.db.session import session_scope

log = logging.getLogger(__name__)

SOURCE_FIELDS = ("label", "doc_id", "doc_version", "title", "location", "chunk_id", "score")


def record(
    question: str,
    result: dict[str, Any] | None,
    *,
    user_id: str | None,
    groups: list[str] | None,
    endpoint: str,
    error: str | None = None,
    engine: Engine | None = None,
) -> None:
    """Store one answer, or the question and ``error`` when answering failed."""
    result = result or {}
    row = AuditRecord(
        user_id=user_id,
        groups=groups,
        endpoint=endpoint,
        question=question,
        search_question=result.get("search_question") or None,
        answer=result.get("answer"),
        found=result.get("found"),
        cached=bool(result.get("cached")),
        sources=[{k: s.get(k) for k in SOURCE_FIELDS} for s in result.get("sources", [])],
        error=error,
        model=result.get("model") or None,
        prompt_version=result.get("prompt_version") or None,
        trace_id=result.get("trace_id"),
    )
    try:
        with session_scope(engine) as session:
            session.add(row)
    except Exception as exc:
        log.warning("audit log write failed: %s", exc)


def prune(retention_days: int, engine: Engine | None = None, now: datetime | None = None) -> int:
    """Delete rows older than ``retention_days``; returns how many were removed."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    with session_scope(engine) as session:
        deleted = session.execute(delete(AuditRecord).where(AuditRecord.created_at < cutoff))
    return int(getattr(deleted, "rowcount", 0) or 0)
