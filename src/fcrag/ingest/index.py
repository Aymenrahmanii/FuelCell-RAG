"""Qdrant collection setup, upserts and stale-chunk cleanup."""

from functools import lru_cache

from qdrant_client import QdrantClient, models

from fcrag.config import get_settings
from fcrag.embedding import Embedding
from fcrag.models import Chunk

DENSE = "dense"
SPARSE = "sparse"
DENSE_SIZE = 1024
KEYWORD_FIELDS = ["system", "doc_type", "doc_id", "language", "kind", "allowed_groups", "doc_sha"]


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url, timeout=60)


def ensure_collection(client: QdrantClient, name: str) -> None:
    if client.collection_exists(name):
        return
    client.create_collection(
        collection_name=name,
        vectors_config={
            DENSE: models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE)
        },
        sparse_vectors_config={SPARSE: models.SparseVectorParams()},
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, always_ram=True)
        ),
    )
    for field in KEYWORD_FIELDS:
        client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "is_latest", models.PayloadSchemaType.BOOL)
    client.create_payload_index(name, "doc_version", models.PayloadSchemaType.INTEGER)


def to_point(chunk: Chunk, embedding: Embedding) -> models.PointStruct:
    sparse = models.SparseVector(
        indices=list(embedding.sparse.keys()), values=list(embedding.sparse.values())
    )
    return models.PointStruct(
        id=chunk.chunk_id,
        vector={DENSE: embedding.dense, SPARSE: sparse},
        payload=chunk.model_dump(mode="json"),
    )


def upsert_chunks(
    client: QdrantClient, name: str, chunks: list[Chunk], embeddings: list[Embedding]
) -> None:
    points = [to_point(c, e) for c, e in zip(chunks, embeddings, strict=True)]
    for start in range(0, len(points), 256):
        client.upsert(name, points=points[start : start + 256], wait=True)


def _match(key: str, value: str | int | bool) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def delete_stale(
    client: QdrantClient, name: str, doc_id: str, doc_version: int, keep_sha: str
) -> None:
    """Remove points of this document version that came from an older file content."""
    client.delete(
        name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[_match("doc_id", doc_id), _match("doc_version", doc_version)],
                must_not=[_match("doc_sha", keep_sha)],
            )
        ),
        wait=True,
    )


def mark_latest(client: QdrantClient, name: str, doc_id: str, latest_version: int) -> None:
    """Flag only the newest version of a document as ``is_latest``."""
    same_doc = _match("doc_id", doc_id)
    client.set_payload(
        name,
        payload={"is_latest": False},
        points=models.Filter(must=[same_doc], must_not=[_match("doc_version", latest_version)]),
        wait=True,
    )
    client.set_payload(
        name,
        payload={"is_latest": True},
        points=models.Filter(must=[same_doc, _match("doc_version", latest_version)]),
        wait=True,
    )
