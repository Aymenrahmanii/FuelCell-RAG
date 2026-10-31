"""Saved evaluation runs for the dashboard: list them, load one with its questions."""

import json
from pathlib import Path
from typing import Any

from fcrag.eval.golden import read_golden

SUMMARY_KEYS = ("recall@5", "recall@10", "mrr", "ndcg@10", "retrieval_p95_s")
ANSWER_KEYS = ("value_accuracy", "citation_precision", "faithfulness", "correct_refusal",
               "false_refusal")  # fmt: skip


def run_files(runs_dir: Path) -> dict[str, Path]:
    """Run name (file stem) to path. Judgement files and anything else are left out."""
    if not runs_dir.is_dir():
        return {}
    return {
        p.stem: p
        for p in sorted(runs_dir.glob("*.json"))
        if not p.name.endswith(".judgements.json")
    }


def list_runs(runs_dir: Path) -> list[dict[str, Any]]:
    """One row per run, newest first: its name, size, config and headline metrics."""
    rows = []
    for name, path in run_files(runs_dir).items():
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
            summary = run["summary"]
        except (json.JSONDecodeError, KeyError, OSError):
            continue  # a half-written or foreign file must not break the dashboard
        answers = summary.get("answers") or {}
        rows.append(
            {
                "name": name,
                "label": run.get("name", name),
                "questions": summary.get("questions"),
                "errors": summary.get("errors", 0),
                **{k: summary.get(k) for k in SUMMARY_KEYS},
                **{k: answers.get(k) for k in ANSWER_KEYS},
                "injection": answers.get("injection"),
                "config": run.get("config", {}),
            }
        )
    return sorted(rows, key=lambda r: r["name"], reverse=True)


def load_run(runs_dir: Path, name: str, golden_path: Path | None = None) -> dict[str, Any] | None:
    """The full run record, each result with its question text; None for an unknown name.

    ``name`` is looked up among the listed files, never joined into a path, so it cannot
    reach outside ``runs_dir``."""
    path = run_files(runs_dir).get(name)
    if path is None:
        return None
    run: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if golden_path is not None and golden_path.exists():
        questions = {i.id: i.question for i in read_golden(golden_path)}
        for result in run.get("results", []):
            result["question"] = questions.get(result.get("id"), "")
    return run
