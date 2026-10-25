"""Score the extracted parameters table against the generator's facts."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select

from fcrag.db.models import ParameterRecord
from fcrag.db.session import session_scope
from fcrag.units import convert_value


def evaluate_parameters(engine: Engine, facts_path: Path) -> dict[str, Any]:
    """Recall: facts with a matching record. Precision: records matching some fact.
    A match has the same document version, component and key, and the same normalised value."""
    facts = [json.loads(line) for line in facts_path.open(encoding="utf-8") if line.strip()]
    with session_scope(engine) as session:
        records = session.scalars(select(ParameterRecord)).all()
        rows = [(r.doc_id, r.doc_version, r.component, r.parameter, r.value_norm) for r in records]

    by_key: dict[tuple[str, int, str | None, str], list[float]] = defaultdict(list)
    for doc_id, version, component, key, value in rows:
        by_key[(doc_id, version, component, key)].append(value)

    def stated(fact: dict[str, Any]) -> float:
        value = convert_value(fact["stated_value"], fact["stated_unit"], fact["truth_unit"])
        return fact["stated_value"] if value is None else value

    def close(a: float, b: float) -> bool:
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))

    report: dict[str, Any] = {"by_doc_type": {}}
    groups: dict[str, list[bool]] = defaultdict(list)
    fact_values: dict[tuple[str, int, str | None, str], list[float]] = defaultdict(list)
    for f in facts:
        ident = (f["doc_id"], f["doc_version"], f["component"], f["key"])
        fact_values[ident].append(stated(f))
        hit = any(close(v, stated(f)) for v in by_key.get(ident, []))
        groups[f["doc_id"].split("-")[0]].append(hit)
    correct = sum(
        any(close(value, v) for v in fact_values.get((d, ver, c, k), []))
        for d, ver, c, k, value in rows
        if (d, ver) in {(f["doc_id"], f["doc_version"]) for f in facts}
    )
    in_scope = [r for r in rows if (r[0], r[1]) in {(f["doc_id"], f["doc_version"]) for f in facts}]
    all_hits = [h for hits in groups.values() for h in hits]
    report["facts"] = len(facts)
    report["records"] = len(in_scope)
    report["recall"] = sum(all_hits) / len(all_hits) if all_hits else 0.0
    report["precision"] = correct / len(in_scope) if in_scope else 0.0
    for prefix, hits in sorted(groups.items()):
        report["by_doc_type"][prefix] = {"facts": len(hits), "recall": sum(hits) / len(hits)}
    return report
