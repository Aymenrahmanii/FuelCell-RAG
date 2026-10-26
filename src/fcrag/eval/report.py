"""Render saved evaluation runs as one Markdown table (the README's ablation table)."""

import json
from pathlib import Path
from typing import Any

COLUMNS = [
    ("recall@5", "Recall@5"),
    ("recall@10", "Recall@10"),
    ("mrr", "MRR"),
    ("ndcg@10", "nDCG@10"),
    ("retrieval_refusal_correct", "Correct refusals"),
    ("retrieval_refusal_false", "False refusals"),
    ("retrieval_p95_s", "Retrieval p95 (s)"),
]
ANSWER_COLUMNS = [
    ("faithfulness", "Faithfulness (judge)"),
    ("value_accuracy", "Value accuracy"),
    ("citation_precision", "Citation precision"),
    ("correct_refusal", "Correct refusals (answers)"),
]


def _fmt(value: Any) -> str:
    return "–" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


def load_runs(runs_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text("utf-8")) for p in sorted(runs_dir.glob("*.json"))]


def markdown(runs: list[dict[str, Any]]) -> str:
    """One row per run; config values that differ between runs become extra columns."""
    if not runs:
        return "_No runs yet._"
    keys = sorted({k for r in runs for k in r["config"]})
    varying = [k for k in keys if len({json.dumps(r["config"].get(k)) for r in runs}) > 1]
    with_answers = any("answers" in r["summary"] for r in runs)
    header = ["Run", "Questions", *varying, *(t for _, t in COLUMNS)]
    if with_answers:
        header += [t for _, t in ANSWER_COLUMNS]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in runs:
        s = r["summary"]
        row = [r["name"], str(s["questions"]), *(_fmt(r["config"].get(k)) for k in varying)]
        row += [_fmt(s.get(k)) for k, _ in COLUMNS]
        if with_answers:
            answers = s.get("answers", {})
            row += [_fmt(answers.get(k)) for k, _ in ANSWER_COLUMNS]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
