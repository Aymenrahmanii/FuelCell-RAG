"""FastAPI service. Stateless: all state lives in Qdrant and Postgres, so replicas scale out.

Models load on first use, so ``/health`` answers immediately after start-up.
"""

import io
import json
import secrets
from collections.abc import Iterator
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from fcrag import __version__
from fcrag.config import get_settings
from fcrag.db.models import Document, Feedback
from fcrag.db.session import get_engine, session_scope
from fcrag.generation.answer import RagService
from fcrag.retrieval.search import Filters


def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().api_key
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


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    systems: list[str] = Field(default_factory=list)
    doc_types: list[str] = Field(default_factory=list)
    latest_only: bool = False

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
    return asdict(service.answer(req.question, req.filters(groups)))


@app.post("/ask/stream")
def ask_stream(req: AskRequest, service: Service, groups: Groups) -> StreamingResponse:
    """Server-sent events: ``sources``, then ``token`` events, then ``done`` (or ``error``)."""

    def events() -> Iterator[str]:
        try:
            for event in service.stream(req.question, req.filters(groups)):
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
