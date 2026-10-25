from dataclasses import asdict
from pathlib import Path

import pytest

from fcrag.eval import metrics
from fcrag.eval.golden import build_golden, read_golden
from fcrag.eval.matching import matches
from fcrag.eval.numbers import extract_quantities, parse_number, value_found


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        ("25,000", "en", 25000), ("25.000", "de", 25000), ("2,6", "de", 2.6), ("2.6", "en", 2.6),
        ("0,35", "de", 0.35), ("1,234.5", "en", 1234.5), ("1.234,5", "de", 1234.5),
        ("25 000", "en", 25000), ("−25", "en", -25), ("2.6", "de", 2.6),
    ],
)  # fmt: skip
def test_parse_number(text: str, language: str, expected: float) -> None:
    assert parse_number(text, language) == pytest.approx(expected)


def test_value_found_with_unit_conversion() -> None:
    assert value_found("The limit is 85 °C [S1].", 85, "degC", "en")
    assert value_found("Grenze: 358,15 K.", 85, "degC", "de")
    assert value_found("Druck 2,2 bar (absolut)", 220, "kPa", "de")
    assert value_found("It draws 18,000 W.", 18, "kW", "en")
    assert value_found("The stack has 440 cells.", 440, "-", "en")
    assert value_found("Lebensdauer 25.000 h", 25000, "h", "de")
    assert not value_found("The limit is 95 °C.", 85, "degC", "en")
    assert not value_found("REQ-A-0085 applies.", 85, "degC", "en")


def test_extract_ignores_incompatible_units() -> None:
    quantities = extract_quantities("80 kW at 2.5 bar and 44 %", "en")
    assert [(q.value, q.unit) for q in quantities] == [(80, "kW"), (2.5, "bar"), (44, "%")]
    assert not value_found("80 kW", 80, "kPa", "en")


def test_matching_by_locator() -> None:
    row = {"doc_id": "ps-a", "doc_version": 2, "locator": {"sheet": "Stack", "cells": "A7:E7"}}
    table = {"doc_id": "ps-a", "doc_version": 2, "locator": {"sheet": "Stack", "cells": "A4:E30"}}
    gold = {"doc_id": "ps-a", "doc_version": 2, "locator": {"sheet": "Stack", "cells": "A7:E7"}}
    assert matches(row, gold) and matches(table, gold)
    assert not matches({**row, "doc_version": 1}, gold)
    assert not matches({**row, "locator": {"sheet": "Stack", "cells": "A8:E8"}}, gold)

    chunk = {"doc_id": "ds", "doc_version": 1, "locator": {"page": 1, "pages": [1, 2]}}
    assert matches(chunk, {"doc_id": "ds", "locator": {"page": 2}})
    assert not matches(chunk, {"doc_id": "ds", "locator": {"page": 3}})
    req = {"doc_id": "req", "doc_version": 1, "locator": {"req_id": "REQ-A-0001"}}
    assert matches(req, {"doc_id": "req", "locator": {"req_id": "REQ-A-0001"}})
    assert matches(req, {"doc_id": "req"})


def test_ranking_metrics() -> None:
    ranks = [1, 3, None, 6]
    assert metrics.recall_at_k(ranks, 5) == 0.5
    assert metrics.mrr(ranks) == pytest.approx((1 + 1 / 3 + 1 / 6) / 4)
    assert metrics.ndcg_at_k([True, False, False]) == 1.0
    assert metrics.ndcg_at_k([False, True]) == pytest.approx(1 / 1.584962500721156)
    assert metrics.ndcg_at_k([False, False]) == 0.0


def test_refusal_detection() -> None:
    assert metrics.is_refusal("The documents do not state a warranty period.")
    assert metrics.is_refusal("Dazu habe ich in den Dokumenten nichts gefunden.") is False
    assert metrics.is_refusal("Die Dokumente enthalten keine Angaben zum Schallpegel.")
    assert not metrics.is_refusal("The maximum coolant outlet temperature is 85 °C [S1].")


def test_committed_golden_set_is_current(repo_root: Path) -> None:
    """Rebuild from the truths; if this fails, run `fcrag golden` and commit the result."""
    rebuilt = build_golden(repo_root / "data_gen/systems", repo_root / "eval/golden_public.yaml")
    committed = read_golden(repo_root / "eval/golden_set.jsonl")
    assert [asdict(i) for i in committed] == [asdict(i) for i in rebuilt]


def test_golden_set_shape(repo_root: Path) -> None:
    items = read_golden(repo_root / "eval/golden_set.jsonl")
    assert len({i.id for i in items}) == len(items) >= 50
    assert sum(i.language == "de" for i in items) >= len(items) // 3
    for item in items:
        if item.answerable:
            assert item.gold_sources, item.id
            assert item.expected_values or item.expected_terms, item.id
        else:
            assert not item.gold_sources, item.id


def test_report_shows_varying_config_only() -> None:
    from fcrag.eval.report import markdown

    base = {"questions": 2, "recall@5": 0.5, "mrr": 0.4}
    runs = [
        {"name": "a", "config": {"chunk_strategy": "fixed", "llm": "x"}, "summary": base},
        {"name": "b", "config": {"chunk_strategy": "section", "llm": "x"},
         "summary": {**base, "recall@5": 0.75}},
    ]  # fmt: skip
    table = markdown(runs).splitlines()
    assert table[0].startswith("| Run | Questions | chunk_strategy | Recall@5")
    assert "llm" not in table[0]
    assert table[3].startswith("| b | 2 | section | 0.750 |")


def test_gate(tmp_path: Path) -> None:
    from fcrag.eval.gate import check_gate, gate_categories

    gate = tmp_path / "gate.yaml"
    gate.write_text(
        "categories: [parameter]\nmin: {recall@5: 0.8}\nmax: {retrieval_refusal_false: 0.05}\n",
        encoding="utf-8",
    )
    assert gate_categories(gate) == ["parameter"]
    assert check_gate({"recall@5": 0.9, "retrieval_refusal_false": 0.0}, gate) == []
    assert check_gate({"recall@5": 0.7, "retrieval_refusal_false": 0.1}, gate) == [
        "recall@5 = 0.7 < 0.8",
        "retrieval_refusal_false = 0.1 > 0.05",
    ]
