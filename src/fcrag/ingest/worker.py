"""Background ingestion on a Redis queue (RQ). The API enqueues; workers scale horizontally."""

import sys
from typing import Any

from redis import Redis
from rq import Queue, Worker

from fcrag.config import get_settings

QUEUE = "ingest"
JOB_TIMEOUT_S = 6 * 3600


def _redis() -> Redis:
    return Redis.from_url(get_settings().redis_url.get_secret_value())


def ingest_job(force: bool = False, only: str | None = None) -> dict[str, int]:
    from fcrag.ingest.pipeline import ingest_all

    return ingest_all(get_settings(), force=force, only=only)


def enqueue_ingest(force: bool = False, only: str | None = None) -> str:
    job = Queue(QUEUE, connection=_redis()).enqueue(
        ingest_job, force=force, only=only, job_timeout=JOB_TIMEOUT_S
    )
    return str(job.id)


def job_status(job_id: str) -> dict[str, Any]:
    job = Queue(QUEUE, connection=_redis()).fetch_job(job_id)
    if job is None:
        return {"id": job_id, "status": "unknown"}
    status: dict[str, Any] = {"id": job_id, "status": str(job.get_status())}
    if job.is_finished:
        status["result"] = job.return_value()
    elif job.is_failed:
        status["error"] = (job.exc_info or "").strip().splitlines()[-1:]
    return status


def run_worker() -> None:
    worker_class: Any = Worker
    if sys.platform == "win32":  # RQ forks per job; Windows has no fork
        from rq import SimpleWorker

        worker_class = SimpleWorker
    worker_class([QUEUE], connection=_redis()).work()
