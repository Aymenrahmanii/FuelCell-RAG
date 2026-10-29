"""Run the golden set against the live pipeline and record the results.

Retrieval metrics always run. Answer metrics (values, terms, citations, refusals) run when an LLM
is available. Each run is saved with its configuration, so runs can be compared one variable
at a time.
"""

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fcrag.config import Settings
from fcrag.eval import metrics
from fcrag.eval.golden import GoldenItem
from fcrag.eval.matching import matches
from fcrag.eval.numbers import value_found
from fcrag.generation.answer import RagService, Timings, load_prompt
from fcrag.generation.citations import normalise_citations
from fcrag.retrieval.search import Filters

CONFIG_FIELDS = (
    "embedding_model", "reranker_model", "chunk_strategy", "chunk_max_tokens",
    "chunk_fixed_tokens", "contextual_headers", "prefetch_limit", "rerank_top_k",
    "rerank_threshold", "llm_model",
)  # fmt: skip


@dataclass
class ItemResult:
    id: str
    category: str
    language: str
    answerable: bool
    rank: int | None = None
    ndcg10: float = 0.0
    top_score: float = 0.0
    """Best reranker score: used to calibrate the not-found threshold."""
    evidence: bool = False
    """At least one chunk passed the rerank threshold."""
    top: list[str] = field(default_factory=list)
    retrieval_s: float = 0.0
    rerank_s: float = 0.0
    """Part of ``retrieval_s``; on CPU, the cross-encoder dominates."""
    candidate_chars: int = 0
    """Text length of all reranked candidates: cross-encoder cost grows with it."""
    candidate_types: dict[str, int] = field(default_factory=dict)
    """Reranked candidates per document type."""
    answer: str | None = None
    refused: bool | None = None
    values_ok: bool | None = None
    terms_ok: bool | None = None
    cited_correct: int = 0
    cited_total: int = 0
    invalid_citations: int = 0
    generation_s: float = 0.0
    model: str | None = None
    """The model that answered (a fallback model if the main one failed)."""
    sources: list[dict[str, Any]] = field(default_factory=list)
    """Label, location and text of every source the answer was given, for the judge."""
    error: str | None = None


def _label(payload: dict[str, Any]) -> str:
    loc = payload.get("locator") or {}
    where = loc.get("req_id") or loc.get("cells") or loc.get("page") or ""
    return f"{payload.get('doc_id')}@v{payload.get('doc_version')}:{where}"


def evaluate_item(
    service: RagService, item: GoldenItem, settings: Settings, *, answers: bool
) -> ItemResult:
    result = ItemResult(item.id, item.category, item.language, item.answerable)
    start = time.perf_counter()
    timings = Timings()
    ranked = service.rank(item.question, Filters(), timings)
    result.retrieval_s = time.perf_counter() - start
    result.rerank_s = timings.rerank_s
    result.candidate_chars = sum(len(h.text) for h in ranked)
    result.candidate_types = dict(Counter(str(h.payload.get("doc_type")) for h in ranked))
    relevance = [any(matches(h.payload, g) for g in item.gold_sources) for h in ranked]
    if item.gold_sources:
        result.rank = metrics.first_hit_rank(relevance)
        result.ndcg10 = metrics.ndcg_at_k(relevance, 10)
    result.top_score = round(max((h.rerank_score or 0.0 for h in ranked), default=0.0), 4)
    result.evidence = result.top_score >= settings.rerank_threshold
    result.top = [_label(h.payload) for h in ranked[:5]]

    if not answers:
        return result
    start = time.perf_counter()
    try:
        answer = service.answer(item.question)
    except Exception as exc:  # keep the retrieval metrics; answer metrics skip this question
        result.error = f"{type(exc).__name__}: {exc}"[:500]
        return result
    result.generation_s = time.perf_counter() - start - answer.timings.embed_s
    result.answer = answer.answer
    result.model = answer.model
    result.sources = [
        {
            "label": s.label,
            "title": s.title,
            "doc_version": s.doc_version,
            "is_latest": s.is_latest,
            "location": s.location,
            "text": s.text,  # full chunk: a truncated source makes the judge miss evidence
        }
        for s in answer.sources
    ]
    result.refused = not answer.found or metrics.is_refusal(answer.answer)
    if item.expected_values:
        result.values_ok = all(
            value_found(answer.answer, v["value"], v["unit"], item.language)
            for v in item.expected_values
        )
    if item.expected_terms:
        lowered = normalise_citations(answer.answer).lower()
        result.terms_ok = all(t.lower() in lowered for t in item.expected_terms)
    cited = [answer.sources[n - 1] for n in answer.cited]
    result.cited_total = len(cited)
    result.cited_correct = sum(any(matches(asdict(s), g) for g in item.gold_sources) for s in cited)
    result.invalid_citations = len(answer.invalid_citations)
    return result


def summarize(results: list[ItemResult]) -> dict[str, Any]:
    with_gold = [r for r in results if r.answerable and r.category != "unanswerable"]
    ranks = [r.rank for r in with_gold]
    summary: dict[str, Any] = {
        "questions": len(results),
        "recall@5": metrics.recall_at_k(ranks, 5),
        "recall@10": metrics.recall_at_k(ranks, 10),
        "mrr": metrics.mrr(ranks),
        "ndcg@10": metrics.mean([r.ndcg10 for r in with_gold]),
        "retrieval_refusal_correct": metrics.mean(
            [0.0 if r.evidence else 1.0 for r in results if not r.answerable]
        ),
        "retrieval_refusal_false": metrics.mean(
            [0.0 if r.evidence else 1.0 for r in results if r.answerable]
        ),
        "retrieval_p50_s": metrics.percentile([r.retrieval_s for r in results], 50),
        "retrieval_p95_s": metrics.percentile([r.retrieval_s for r in results], 95),
        "rerank_p50_s": metrics.percentile([r.rerank_s for r in results], 50),
        "candidate_chars_p50": metrics.percentile([r.candidate_chars for r in results], 50),
        "by_category": {},
    }
    for category in sorted({r.category for r in results}):
        rows = [r for r in results if r.category == category]
        cat_ranks = [r.rank for r in rows if r.answerable]
        summary["by_category"][category] = {
            "n": len(rows),
            "recall@5": metrics.recall_at_k(cat_ranks, 5) if cat_ranks else None,
        }

    answered = [r for r in results if r.answer is not None]
    failed = sum(1 for r in results if r.error)
    summary["errors"] = failed
    if answered:
        valued = [r.values_ok for r in answered if r.values_ok is not None]
        termed = [r.terms_ok for r in answered if r.terms_ok is not None]
        cited = sum(r.cited_total for r in answered)
        summary["answers"] = {
            "value_accuracy": metrics.mean([1.0 if v else 0.0 for v in valued]),
            "term_accuracy": metrics.mean([1.0 if t else 0.0 for t in termed]),
            "citation_precision": sum(r.cited_correct for r in answered) / cited if cited else 0.0,
            "invalid_citations": sum(r.invalid_citations for r in answered),
            "correct_refusal": metrics.mean(
                [1.0 if r.refused else 0.0 for r in answered if not r.answerable]
            ),
            "false_refusal": metrics.mean(
                [1.0 if r.refused else 0.0 for r in answered if r.answerable]
            ),
            "generation_p95_s": metrics.percentile([r.generation_s for r in answered], 95),
            "models": dict(Counter(r.model or "none" for r in answered)),
        }
    return summary


def rescore(run_data: dict[str, Any], items: list[GoldenItem]) -> dict[str, Any]:
    """Recompute answer metrics of a saved run from its stored answers, with the current
    scoring code. Needs no LLM, so metric fixes do not cost free-tier quota."""
    by_id = {i.id: i for i in items}
    not_found = {t for t in load_prompt()["not_found"].values()}
    results = []
    for raw in run_data["results"]:
        r = ItemResult(**{k: v for k, v in raw.items() if k in ItemResult.__dataclass_fields__})
        item = by_id.get(r.id)
        if item is not None and r.answer is not None:
            text = normalise_citations(r.answer)
            r.refused = r.answer in not_found or metrics.is_refusal(text)
            expected = item.expected_values
            r.values_ok = (
                all(value_found(text, v["value"], v["unit"], item.language) for v in expected)
                if expected
                else None
            )
            r.terms_ok = (
                all(t.lower() in text.lower() for t in item.expected_terms)
                if item.expected_terms else None
            )  # fmt: skip
        results.append(r)
    out = dict(run_data)
    out["summary"] = summarize(results) | {
        k: v for k, v in run_data["summary"].items() if k == "judge"
    }
    if "judge" in run_data["summary"] and "answers" in out["summary"]:
        out["summary"]["answers"]["faithfulness"] = run_data["summary"]["answers"].get(
            "faithfulness"
        )
    out["results"] = [asdict(r) for r in results]
    return out


def run(
    service: RagService,
    items: list[GoldenItem],
    settings: Settings,
    *,
    name: str,
    answers: bool,
    out_dir: Path,
    pause_s: float = 0.0,
) -> tuple[dict[str, Any], Path]:
    """``pause_s`` waits between answered questions, to stay under a free tier's rate limit."""
    results = []
    for n, item in enumerate(items):
        if answers and pause_s and n:
            time.sleep(pause_s)
        try:
            results.append(evaluate_item(service, item, settings, answers=answers))
        except Exception as exc:  # one broken question must not hide the rest of the run
            failed = ItemResult(item.id, item.category, item.language, item.answerable)
            failed.error = f"{type(exc).__name__}: {exc}"
            results.append(failed)
    summary = summarize(results)
    record = {
        "name": name,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": {k: getattr(settings, k) for k in CONFIG_FIELDS},
        "answers": answers,
        "summary": summary,
        "results": [asdict(r) for r in results],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    path = out_dir / f"{stamp}-{name}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), "utf-8")
    return summary, path
