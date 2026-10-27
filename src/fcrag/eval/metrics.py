"""Retrieval and answer metrics. Pure functions over per-question results."""

import math
import re
import statistics
from collections.abc import Sequence

REFUSAL = re.compile(
    r"\b(not (?:find|found|contain|state|mention|include|specif|give|provide|name)|no information"
    r"|nicht (?:gefunden|enthalten|angegeben|genannt)|keine (?:Angabe|Information|Preis|Kosten)"
    r"|enthalten keine|nennen keine|do(?:es)? not (?:state|contain|specify|give|name|mention))",
    re.IGNORECASE,
)


def first_hit_rank(relevance: Sequence[bool]) -> int | None:
    """1-based rank of the first relevant result, or None."""
    return next((i for i, rel in enumerate(relevance, 1) if rel), None)


def recall_at_k(ranks: Sequence[int | None], k: int) -> float:
    """Share of questions with at least one gold source in the top ``k``."""
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def mrr(ranks: Sequence[int | None]) -> float:
    return sum(1 / r for r in ranks if r is not None) / len(ranks) if ranks else 0.0


def ndcg_at_k(relevance: Sequence[bool], k: int = 10) -> float:
    """Binary-relevance nDCG; the ideal ranking puts every relevant result found on top."""
    dcg = sum(1 / math.log2(i + 1) for i, rel in enumerate(relevance[:k], 1) if rel)
    n_relevant = min(sum(relevance), k)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, n_relevant + 1))
    return dcg / ideal if ideal else 0.0


def is_refusal(answer: str) -> bool:
    """True if the answer opens by saying the documents lack the information. A later remark
    such as "the parameter list has no row for X" does not make a correct answer a refusal."""
    first = re.split(r"(?<=[.!?])\s+", answer.strip(), maxsplit=1)[0]
    return bool(REFUSAL.search(first))


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
