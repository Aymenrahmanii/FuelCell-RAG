"""Query routing: spot parameter questions and answer them from the parameters table.

A question that names a system and a known parameter label ("maximum coolant outlet temperature
of System B") gets the matching records as exact, citable sources. Hybrid search still runs, so
the answer can add context; the structured records just make the number reliable.
"""

import re
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import Engine, select

from fcrag.db.models import Document, ParameterRecord
from fcrag.db.session import session_scope
from fcrag.ingest.extract_params import Vocabulary, normalise_label

SYSTEMS = re.compile(
    r"\bSystem(?:s|e)?\s+([A-Z](?:\s*(?:,|and|und|or|oder|&|/)\s*(?:System\s+)?[A-Z])*)\b"
)
"""``System B``, ``Systems A and C``, ``Systeme A und C``."""
MAX_RECORDS = 6


@dataclass
class Route:
    systems: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)

    @property
    def is_parameter_query(self) -> bool:
        return bool(self.systems and self.keys)


def detect(question: str, vocab: Vocabulary) -> Route:
    systems: list[str] = []
    for match in SYSTEMS.finditer(question):
        for letter in re.findall(r"\b[A-Z]\b", match.group(1)):
            name = f"System {letter}"
            if name in vocab.systems and name not in systems:
                systems.append(name)
    norm = f" {normalise_label(question)} "
    keys: list[str] = []
    covered: list[str] = []
    # Longest labels first; skip labels inside an already matched longer one.
    for label, key in sorted(vocab.labels.items(), key=lambda kv: -len(kv[0])):
        if len(label) < 6 or f" {label} " not in norm or any(label in c for c in covered):
            continue
        covered.append(label)
        if key not in keys:
            keys.append(key)
    return Route(systems, keys)


@dataclass
class ParameterHit:
    record: ParameterRecord
    title: str
    is_latest: bool


class ParameterStore(Protocol):
    def lookup(
        self, systems: list[str], keys: list[str], *, limit: int | None = ...
    ) -> list[ParameterHit]: ...


class SqlParameterStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def lookup(
        self, systems: list[str], keys: list[str], *, limit: int | None = MAX_RECORDS
    ) -> list[ParameterHit]:
        """Records for these systems and keys, every document version, newest first.
        ``limit`` is per system; None returns everything."""
        with session_scope(self.engine) as session:
            rows = session.execute(
                select(ParameterRecord, Document.title)
                .outerjoin(
                    Document,
                    (Document.doc_id == ParameterRecord.doc_id)
                    & (Document.doc_version == ParameterRecord.doc_version),
                )
                .where(ParameterRecord.system.in_(systems), ParameterRecord.parameter.in_(keys))
                .order_by(ParameterRecord.doc_version.desc(), ParameterRecord.doc_id)
            ).all()
        latest: dict[str, int] = {}
        for record, _ in rows:
            latest[record.doc_id] = max(latest.get(record.doc_id, 0), record.doc_version)
        seen: set[tuple[str, int, str | None, str, str]] = set()
        hits = []
        for record, title in rows:
            ident = (record.doc_id, record.doc_version, record.component, record.parameter,
                     record.system)  # fmt: skip
            if ident in seen:
                continue
            seen.add(ident)
            hits.append(
                ParameterHit(
                    record, title or record.doc_id, record.doc_version == latest[record.doc_id]
                )
            )
        return hits if limit is None else hits[: limit * max(1, len(systems))]
