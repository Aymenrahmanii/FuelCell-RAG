"""bge-m3 embeddings: one forward pass gives a dense vector and sparse lexical weights.

Shared by ingestion (documents) and retrieval (queries), so both always use the same model.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

from fcrag.config import get_settings


@dataclass
class Embedding:
    dense: list[float]
    sparse: dict[int, float] = field(default_factory=dict)
    """Token id to weight, as produced by bge-m3's lexical head."""


class Embedder(Protocol):
    def embed(self, texts: list[str], *, max_tokens: int | None = None) -> list[Embedding]: ...


class BgeM3Embedder:
    def __init__(self, model_name: str, batch_size: int = 32, max_tokens: int = 1024) -> None:
        import torch
        from FlagEmbedding import BGEM3FlagModel

        cuda = torch.cuda.is_available()
        self._model: Any = BGEM3FlagModel(
            model_name, use_fp16=cuda, devices="cuda:0" if cuda else "cpu"
        )
        self._batch_size = batch_size
        self._max_tokens = max_tokens

    def embed(self, texts: list[str], *, max_tokens: int | None = None) -> list[Embedding]:
        if not texts:
            return []
        out = self._model.encode(
            texts,
            batch_size=self._batch_size,
            max_length=max_tokens or self._max_tokens,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        return [
            Embedding(
                dense=[float(x) for x in dense],
                sparse={int(token): float(weight) for token, weight in lexical.items()},
            )
            for dense, lexical in zip(out["dense_vecs"], out["lexical_weights"], strict=True)
        ]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    s = get_settings()
    return BgeM3Embedder(s.embedding_model, s.embedding_batch_size, s.embedding_max_tokens)
