"""CI quality gate: compare a run's summary with the thresholds in ``eval/gate.yaml``."""

from pathlib import Path
from typing import Any

import yaml


def check_gate(summary: dict[str, Any], gate_path: Path) -> list[str]:
    """Returns the violated thresholds; empty means the gate passes."""
    gate = yaml.safe_load(gate_path.read_text(encoding="utf-8"))
    failures = []
    for metric, minimum in (gate.get("min") or {}).items():
        value = summary.get(metric)
        if value is None or value < minimum:
            failures.append(f"{metric} = {value} < {minimum}")
    for metric, maximum in (gate.get("max") or {}).items():
        value = summary.get(metric)
        if value is None or value > maximum:
            failures.append(f"{metric} = {value} > {maximum}")
    return failures


def gate_categories(gate_path: Path) -> list[str]:
    gate = yaml.safe_load(gate_path.read_text(encoding="utf-8"))
    return list(gate.get("categories") or [])
