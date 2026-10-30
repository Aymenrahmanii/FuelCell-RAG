"""Hybrid retrieval: dense and sparse prefetch in Qdrant, fused with reciprocal rank fusion."""

from dataclasses import dataclass, field
from typing import Any

from qdrant_client import QdrantClient, models

from fcrag.embedding import Embedding
from fcrag.ingest.index import DENSE, SPARSE


@dataclass
class Filters:
    systems: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    latest_only: bool = False
    """Off by default: the answer should show conflicting versions, labelled, not hide them."""
    groups: list[str] | None = None
    """The caller's access groups. Documents without ``allowed_groups`` are visible to everyone."""
    named_systems: list[str] = field(default_factory=list)
    """Systems the question names. Unlike ``systems``, documents that belong to no system (public
    reports) stay in: only other systems' documents are dropped."""


@dataclass
class Hit:
    chunk_id: str
    score: float
    payload: dict[str, Any]
    rerank_score: float | None = None

    @property
    def text(self) -> str:
        return str(self.payload.get("text", ""))


def build_filter(filters: Filters) -> models.Filter | None:
    must: list[models.Condition] = []
    if filters.systems:
        must.append(models.FieldCondition(key="system", match=models.MatchAny(any=filters.systems)))
    if filters.doc_types:
        must.append(
            models.FieldCondition(key="doc_type", match=models.MatchAny(any=filters.doc_types))
        )
    if filters.named_systems:
        must.append(
            models.Filter(
                should=[
                    models.FieldCondition(
                        key="system", match=models.MatchAny(any=filters.named_systems)
                    ),
                    models.IsEmptyCondition(is_empty=models.PayloadField(key="system")),
                ]
            )
        )
    if filters.latest_only:
        must.append(models.FieldCondition(key="is_latest", match=models.MatchValue(value=True)))
    if filters.groups is not None:
        must.append(
            models.Filter(
                should=[
                    models.IsEmptyCondition(is_empty=models.PayloadField(key="allowed_groups")),
                    models.FieldCondition(
                        key="allowed_groups", match=models.MatchAny(any=filters.groups)
                    ),
                ]
            )
        )
    return models.Filter(must=must) if must else None


def hybrid_search(
    client: QdrantClient,
    collection: str,
    query: Embedding,
    filters: Filters,
    *,
    prefetch_limit: int = 50,
    limit: int = 50,
) -> list[Hit]:
    qfilter = build_filter(filters)
    sparse = models.SparseVector(indices=list(query.sparse), values=list(query.sparse.values()))
    response = client.query_points(
        collection,
        prefetch=[
            models.Prefetch(query=query.dense, using=DENSE, limit=prefetch_limit, filter=qfilter),
            models.Prefetch(query=sparse, using=SPARSE, limit=prefetch_limit, filter=qfilter),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    return [Hit(str(p.id), p.score, p.payload or {}) for p in response.points]
