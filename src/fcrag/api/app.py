"""FastAPI service. Stateless: all state lives in Qdrant and Postgres, so replicas scale out.

Models load on first use, so ``/health`` answers immediately after start-up.
"""

import io
import json
import secrets
import time
from collections.abc import Iterator
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from fcrag import __version__, metrics
from fcrag.config import get_settings
from fcrag.db.models import Document, Feedback
from fcrag.db.session import get_engine, session_scope
from fcrag.generation.answer import RagService
from fcrag.generation.rewrite import Turn
from fcrag.retrieval.search import Filters


def require_key(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().api_key
    if request.url.path == "/metrics":
        return  # scraped by Prometheus on the internal network; counts and timings only
    if expected is not None and not secrets.compare_digest(
        x_api_key or "", expected.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


def user_groups(x_user_groups: Annotated[str | None, Header()] = None) -> list[str] | None:
    """Access-control stub until OIDC: comma-separated groups; absent means no restriction."""
    return [g.strip() for g in x_user_groups.split(",") if g.strip()] if x_user_groups else None


@lru_cache(maxsize=1)
def get_service() -> RagService:
    from fcrag.embedding import get_embedder
    from fcrag.ingest.index import get_client
    from fcrag.llm.client import LiteLLMClient
    from fcrag.retrieval.rerank import get_reranker

    s = get_settings()
    from fcrag.db.session import get_engine
    from fcrag.ingest.extract_params import Vocabulary
    from fcrag.retrieval.route import SqlParameterStore

    return RagService(
        s, get_embedder(), get_reranker(), get_client(), LiteLLMClient(s),
        params=SqlParameterStore(get_engine()),
        vocabulary=Vocabulary.from_truth(s.systems_dir, s.synonyms_path),
    )  # fmt: skip


Service = Annotated[RagService, Depends(get_service)]
Groups = Annotated[list[str] | None, Depends(user_groups)]

app = FastAPI(title="FuelCell-RAG", version=__version__, dependencies=[Depends(require_key)])


@app.middleware("http")
async def count_requests(request: Request, call_next: Any) -> Response:
    """Requests and their duration per route template (never the raw path: IDs in URLs would
    create one series per document). For /ask/stream the duration ends at the first byte."""
    start = time.perf_counter()
    status = 500
    try:
        response: Response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        metrics.HTTP_REQUESTS.inc(path=path, method=request.method, status=str(status))
        metrics.HTTP_LATENCY.observe(time.perf_counter() - start, path=path)


def _documents_by_status() -> list[tuple[dict[str, str], float]]:
    with session_scope() as session:
        rows = session.execute(
            select(Document.status, func.count()).group_by(Document.status)
        ).all()
    return [({"status": status}, float(n)) for status, n in rows]


def _ingest_queue_length() -> list[tuple[dict[str, str], float]]:
    from rq import Queue

    from fcrag.ingest.worker import QUEUE, _redis

    return [({}, float(Queue(QUEUE, connection=_redis()).count))]


metrics.register(metrics.Gauge(
    "fcrag_documents", "Registered documents by ingestion status (failed, quarantined, ...).",
    _documents_by_status,
))  # fmt: skip
metrics.register(metrics.Gauge(
    "fcrag_ingest_queue_length", "Ingestion jobs waiting in the queue.", _ingest_queue_length
))  # fmt: skip


@app.get("/metrics", response_class=PlainTextResponse)
def metrics_endpoint() -> str:
    """Prometheus scrape target (no API key: aggregate counts and timings only)."""
    return metrics.render()


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    systems: list[str] = Field(default_factory=list)
    doc_types: list[str] = Field(default_factory=list)
    latest_only: bool = False
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    """Earlier turns of the chat, oldest first; a follow-up question is resolved against them."""

    def turns(self) -> list[Turn]:
        return [{"role": t.role, "content": t.content} for t in self.history]

    def filters(self, groups: list[str] | None) -> Filters:
        return Filters(self.systems, self.doc_types, self.latest_only, groups)


class FeedbackRequest(BaseModel):
    question: str
    answer: str
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=4000)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    model: str | None = None
    prompt_version: str | None = None
    trace_id: str | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    from fcrag.ingest.index import get_client

    status: dict[str, Any] = {"status": "ok", "version": __version__}
    try:
        get_client().get_collections()
        status["qdrant"] = True
    except Exception:
        status["qdrant"], status["status"] = False, "degraded"
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        status["postgres"] = True
    except Exception:
        status["postgres"], status["status"] = False, "degraded"
    return status


@app.post("/search")
def search(req: AskRequest, service: Service, groups: Groups) -> list[dict[str, Any]]:
    return [asdict(s) for s in service.retrieve(req.question, req.filters(groups))]


@app.post("/ask")
def ask(req: AskRequest, service: Service, groups: Groups) -> dict[str, Any]:
    return asdict(service.answer(req.question, req.filters(groups), req.turns()))


@app.post("/ask/stream")
def ask_stream(req: AskRequest, service: Service, groups: Groups) -> StreamingResponse:
    """Server-sent events: ``sources``, then ``token`` events, then ``done`` (or ``error``)."""

    def events() -> Iterator[str]:
        try:
            for event in service.stream(req.question, req.filters(groups), req.turns()):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error = {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
            yield f"data: {json.dumps(error)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/documents")
def documents() -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.scalars(select(Document).order_by(Document.doc_id)).all()
        return [
            {c.name: getattr(r, c.name) for c in Document.__table__.columns if c.name != "path"}
            for r in rows
        ]


@app.get("/documents/{doc_id}/v{version}/pages/{page}.png")
def page_image(doc_id: str, version: int, page: int, scale: float = 1.5) -> Response:
    """Render a cited PDF page, for the source preview next to an answer."""
    import pypdfium2

    with session_scope() as session:
        row = session.get(Document, f"{doc_id}@v{version}")
    if row is None or row.mime_type != "application/pdf" or not Path(row.path).exists():
        raise HTTPException(status_code=404, detail="no PDF for this document version")
    pdf = pypdfium2.PdfDocument(row.path)
    if not 1 <= page <= len(pdf):
        raise HTTPException(status_code=404, detail="page out of range")
    image = pdf[page - 1].render(scale=min(max(scale, 0.5), 3.0)).to_pil()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png")


class CompareRequest(BaseModel):
    systems: list[str] = Field(min_length=1)
    keys: list[str] = Field(min_length=1)


class CheckRequest(BaseModel):
    text: str = Field(min_length=5, max_length=4000)
    system: str | None = None


@app.get("/parameters/keys")
def parameter_keys(service: Service) -> list[dict[str, str]]:
    """Every known parameter with its English and German label and canonical unit."""
    vocab = service.vocabulary
    if vocab is None:
        return []
    seen: dict[str, dict[str, str]] = {}
    for system in vocab.systems.values():
        params = list(system.parameters) + [p for c in system.components for p in c.parameters]
        for p in params:
            seen.setdefault(p.key, {"key": p.key, "label_en": p.label_en,
                                    "label_de": p.label_de, "unit": p.unit})  # fmt: skip
    return sorted(seen.values(), key=lambda p: p["label_en"])


@app.post("/parameters/compare")
def parameters_compare(req: CompareRequest, service: Service) -> dict[str, Any]:
    from fcrag.apps.compare import compare

    if service.params is None:
        raise HTTPException(status_code=503, detail="parameter store not configured")
    table = compare(service.params, req.systems, req.keys)
    return {key: {s: asdict(cell) for s, cell in row.items()} for key, row in table.items()}


@app.post("/requirements/check")
def requirements_check(req: CheckRequest, service: Service, groups: Groups) -> dict[str, Any]:
    """Similar and linked requirements, plus stated values that conflict with the documents."""
    from fcrag.apps.checker import check_requirement

    if service.params is None or service.vocabulary is None:
        raise HTTPException(status_code=503, detail="parameter store not configured")
    system, checks = check_requirement(req.text, req.system, service.vocabulary, service.params)
    filters = Filters(systems=[system] if system else [], doc_types=["requirements"], groups=groups)
    similar = []
    linked: list[str] = []
    for hit in service.rank(req.text, filters)[:5]:
        meta = hit.payload.get("meta") or {}
        similar.append(
            {
                "req_id": meta.get("req_id") or (hit.payload.get("locator") or {}).get("req_id"),
                "doc_id": hit.payload.get("doc_id"),
                "text": hit.text,
                "score": round(hit.rerank_score or 0.0, 4),
                "status": meta.get("status"),
                "parent": meta.get("parent"),
                "links": meta.get("links", []),
            }
        )
        for ref in [meta.get("parent"), *meta.get("links", [])]:
            if ref and ref not in linked:
                linked.append(ref)
    return {
        "system": system,
        "parameters": [asdict(c) for c in checks],
        "similar": similar,
        "linked": linked,
    }


class IngestRequest(BaseModel):
    force: bool = False
    only: list[str] | None = Field(default=None, description="globs on doc_id, e.g. ['ds-*']")


@app.post("/ingest", status_code=202)
def ingest(req: IngestRequest) -> dict[str, str]:
    """Queue a re-ingestion; only new or changed files are processed unless ``force``."""
    from fcrag.ingest.worker import enqueue_ingest

    return {"job_id": enqueue_ingest(force=req.force, only=req.only)}


@app.get("/ingest/{job_id}")
def ingest_status(job_id: str) -> dict[str, Any]:
    from fcrag.ingest.worker import job_status

    return job_status(job_id)


@app.get("/eval/runs")
def eval_runs() -> list[dict[str, Any]]:
    """Saved evaluation runs, newest first, with their headline metrics."""
    from fcrag.eval.store import list_runs

    return list_runs(get_settings().eval_runs_dir)


@app.get("/eval/runs/{name}")
def eval_run(name: str) -> dict[str, Any]:
    """One run with every question's result and question text."""
    from fcrag.eval.store import load_run

    s = get_settings()
    run = load_run(s.eval_runs_dir, name, s.golden_path)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no evaluation run {name!r}")
    return run


@app.post("/feedback", status_code=201)
def feedback(req: FeedbackRequest) -> dict[str, int]:
    from fcrag.observability import score

    with session_scope() as session:
        row = Feedback(**req.model_dump(exclude={"trace_id"}))
        session.add(row)
        session.flush()
        feedback_id = row.id
    if req.trace_id:  # links the rating to the request's trace in Langfuse
        score(req.trace_id, "user_feedback", req.rating, req.comment)
    return {"id": feedback_id}
