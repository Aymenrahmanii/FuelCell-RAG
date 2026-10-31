"""Saved runs for the dashboard: listing, loading with questions, no path escapes."""

import json
from pathlib import Path

from fcrag.eval.store import list_runs, load_run


def _run(path: Path, name: str, recall: float, answers: dict[str, object] | None = None) -> None:
    summary: dict[str, object] = {"questions": 2, "recall@5": recall, "mrr": 0.5}
    if answers:
        summary["answers"] = answers
    record = {
        "name": name, "config": {"prefetch_limit": 50}, "summary": summary,
        "results": [{"id": "param-01", "category": "parameter", "rank": 1}],
    }  # fmt: skip
    path.write_text(json.dumps(record), encoding="utf-8")


def test_list_runs_newest_first_and_skips_broken_files(tmp_path: Path) -> None:
    _run(tmp_path / "2026-10-30-1000-a.json", "a", 0.8)
    _run(tmp_path / "2026-10-31-1000-b.json", "b", 0.9, {"value_accuracy": 0.95})
    (tmp_path / "2026-10-31-1100-half.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "x.judgements.jsonl").write_text("{}", encoding="utf-8")
    rows = list_runs(tmp_path)
    assert [r["name"] for r in rows] == ["2026-10-31-1000-b", "2026-10-30-1000-a"]
    assert rows[0]["value_accuracy"] == 0.95 and rows[1]["value_accuracy"] is None
    assert rows[0]["config"] == {"prefetch_limit": 50}
    assert list_runs(tmp_path / "missing") == []


def test_load_run_adds_questions_and_rejects_other_paths(tmp_path: Path, repo_root: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    _run(runs / "r.json", "r", 1.0)
    (tmp_path / "secret.json").write_text("{}", encoding="utf-8")
    run = load_run(runs, "r", repo_root / "eval/golden_set.jsonl")
    assert run is not None
    assert run["results"][0]["question"] == "How many cells does the System A stack have?"
    assert load_run(runs, "../secret") is None and load_run(runs, "nope") is None
