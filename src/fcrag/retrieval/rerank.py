"""Cross-encoder reranking with bge-reranker-v2-m3 (multilingual)."""

from functools import lru_cache
from typing import Any, Protocol

from fcrag.config import get_settings
from fcrag.retrieval.search import Hit


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]:
        """Relevance of each text to the query, in 0..1."""
        ...


class BgeReranker:
    def __init__(self, model_name: str) -> None:
        import torch
        from FlagEmbedding import FlagReranker

        cuda = torch.cuda.is_available()
        self._model: Any = FlagReranker(
            model_name, use_fp16=cuda, devices="cuda:0" if cuda else "cpu"
        )

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        scores = self._model.compute_score(
            [[query, t] for t in texts], normalize=True, batch_size=16, max_length=1024
        )
        return [float(s) for s in (scores if isinstance(scores, list) else [scores])]


def rerank(
    reranker: Reranker, query: str, hits: list[Hit], *, top_k: int, threshold: float
) -> list[Hit]:
    """Keep the ``top_k`` best hits scoring at least ``threshold``; empty means 'not found'."""
    for hit, score in zip(hits, reranker.score(query, [h.text for h in hits]), strict=True):
        hit.rerank_score = score
    ranked = sorted(hits, key=lambda h: h.rerank_score or 0.0, reverse=True)
    return [h for h in ranked[:top_k] if (h.rerank_score or 0.0) >= threshold]


@lru_cache(maxsize=1)
def get_reranker() -> Reranker:
    return BgeReranker(get_settings().reranker_model)
