"""Parameter comparison across systems (FR-11): one row per parameter, one cell per system."""

from dataclasses import dataclass, field
from typing import Any

from fcrag.generation.citations import format_locator
from fcrag.retrieval.route import ParameterStore
from fcrag.units import display_unit

DOC_PREFERENCE = ("ds-", "ps-", "req-")
"""Datasheet first, then parameter sheet, then requirement, for the headline value."""


@dataclass
class Cell:
    value: float | None
    """Value from the newest version of the preferred document, in the canonical unit."""
    unit: str
    agree: bool
    """All current documents state the same value."""
    sources: list[dict[str, Any]] = field(default_factory=list)


def _rank(doc_id: str) -> int:
    return next((i for i, p in enumerate(DOC_PREFERENCE) if doc_id.startswith(p)), 99)


def compare(
    store: ParameterStore, systems: list[str], keys: list[str]
) -> dict[str, dict[str, Cell]]:
    hits = store.lookup(systems, keys, limit=None)
    table: dict[str, dict[str, Cell]] = {}
    for key in keys:
        table[key] = {}
        for system in systems:
            rows = [h for h in hits if h.record.parameter == key and h.record.system == system]
            current = sorted((h for h in rows if h.is_latest), key=lambda h: _rank(h.record.doc_id))
            values = {round(h.record.value_norm, 6) for h in current}
            table[key][system] = Cell(
                value=current[0].record.value_norm if current else None,
                unit=display_unit(current[0].record.unit_norm) if current else "",
                agree=len(values) <= 1,
                sources=[
                    {
                        "doc_id": h.record.doc_id,
                        "doc_version": h.record.doc_version,
                        "is_latest": h.is_latest,
                        "title": h.title,
                        "value": h.record.value_norm,
                        "stated": f"{h.record.value:g} {display_unit(h.record.unit)}".strip(),
                        "location": format_locator(h.record.locator),
                    }
                    for h in sorted(rows, key=lambda h: (not h.is_latest, _rank(h.record.doc_id)))
                ],
            )
    return table
