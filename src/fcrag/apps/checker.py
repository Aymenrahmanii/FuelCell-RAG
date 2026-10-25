"""Requirement checker (FR-10, FR-11): find values in a draft requirement that conflict with the
documents, by extracting its parameters and comparing them with the parameters table."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fcrag.generation.citations import format_locator
from fcrag.ingest.extract_params import Vocabulary, extract_parameters
from fcrag.language import detect_language
from fcrag.models import Element, SourceFile
from fcrag.retrieval.route import ParameterStore, detect
from fcrag.units import display_unit

REL_TOL = 0.005


@dataclass
class ParameterCheck:
    parameter: str
    label: str
    component: str | None
    stated: str
    value_norm: float
    unit_norm: str
    status: str
    """``conflict``, ``consistent`` or ``unknown`` (no document states it)."""
    documents: list[dict[str, Any]] = field(default_factory=list)


def _agrees(a: float, b: float) -> bool:
    return abs(a - b) <= REL_TOL * max(1.0, abs(b))


def check_requirement(
    text: str, system: str | None, vocab: Vocabulary, store: ParameterStore
) -> tuple[str | None, list[ParameterCheck]]:
    """Returns the system used and one check per parameter found in ``text``."""
    if system is None:
        detected = detect(text, vocab).systems
        system = detected[0] if detected else None
    if system is None:
        return None, []
    source = SourceFile(
        path=Path("draft"),
        sha256="0" * 64,
        mime_type="text/plain",
        doc_id="draft",
        system=system,
        language=detect_language(text),
    )
    element = Element(kind="requirement", content=text, data={"text": text})
    checks = []
    for record in extract_parameters(vocab, source, [element]):
        current = [
            h
            for h in store.lookup([system], [record.parameter], limit=None)
            if h.is_latest and (record.component is None or h.record.component == record.component)
        ]
        documents = [
            {
                "doc_id": h.record.doc_id,
                "doc_version": h.record.doc_version,
                "title": h.title,
                "value": h.record.value_norm,
                "location": format_locator(h.record.locator),
                "agrees": _agrees(h.record.value_norm, record.value_norm),
            }
            for h in current
        ]
        if not documents:
            status = "unknown"
        elif all(d["agrees"] for d in documents):
            status = "consistent"
        else:
            status = "conflict"
        checks.append(
            ParameterCheck(
                parameter=record.parameter,
                label=record.label,
                component=record.component,
                stated=f"{record.value:g} {display_unit(record.unit)}".strip(),
                value_norm=record.value_norm,
                unit_norm=display_unit(record.unit_norm),
                status=status,
                documents=documents,
            )
        )
    return system, checks
