"""The smoke-test questions must stay in sync with the system truths."""

import json
from pathlib import Path
from typing import Any

import pytest

from fcrag.truth import SystemTruth, parse_unit

CATEGORIES = {"parameter", "fact_text", "cross_system", "version_conflict", "unanswerable"}


@pytest.fixture(scope="module")
def questions(repo_root: Path) -> list[dict[str, Any]]:
    path = repo_root / "eval" / "smoke_questions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_shape(questions: list[dict[str, Any]]) -> None:
    assert len(questions) == 20
    assert len({q["id"] for q in questions}) == 20
    assert {q["category"] for q in questions} == CATEGORIES
    german = sum(q["language"] == "de" for q in questions)
    assert german >= len(questions) // 3, "about a third of the questions should be German"


def test_truth_refs_match_yaml(
    questions: list[dict[str, Any]], systems: dict[str, SystemTruth]
) -> None:
    for q in questions:
        for ref in q["truth_refs"]:
            truth = systems[ref["system"]].lookup(ref["key"], ref["component"])
            assert truth.value == pytest.approx(ref["value"]), q["id"]
            assert parse_unit(truth.unit) == parse_unit(ref["unit"]), q["id"]


def test_parameter_questions_have_refs(questions: list[dict[str, Any]]) -> None:
    for q in questions:
        if q["category"] in {"parameter", "cross_system", "version_conflict"}:
            assert q["truth_refs"], f"{q['id']} needs truth_refs"
        if q["category"] == "unanswerable":
            assert not q["truth_refs"], q["id"]
