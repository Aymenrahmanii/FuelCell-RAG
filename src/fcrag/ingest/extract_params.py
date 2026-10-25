"""Structured parameter extraction: table rows and prose sentences become validated records.

A vocabulary built from the system truths (English and German labels, plus extra synonyms in
``data_gen/synonyms.yaml``) maps a label such as "Betriebstemperatur" or "Maximum coolant outlet
temperature" to a canonical key. Units are validated and normalised with pint to the key's
canonical unit, so "368.15 K" and "95 °C" become the same record value.

This rule-based pass covers tables and the sentence patterns of engineering documents; an LLM
pass with a Pydantic schema can be added for free text that it misses.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from fcrag.eval.numbers import extract_quantities, parse_number
from fcrag.models import Element, Parameter, SourceFile
from fcrag.truth import SystemTruth, load_all
from fcrag.units import convert_value, to_pint

COMPONENT_ID = re.compile(r"\b([A-Z])-(STK|CMP|BLW|HUM|CLP|HRB)\b")
VALUE_COLUMNS = {"value", "wert", "operating point / value", "betriebspunkt / wert"}
UNIT_COLUMNS = {"unit", "einheit", "operating point / unit", "betriebspunkt / einheit"}
NAME_COLUMNS = {"name", "bezeichnung", "parameter", "parameter / name", "parameter / bezeichnung"}
CONDITION_COLUMNS = {"condition", "bedingung", "operating point / condition",
                     "betriebspunkt / bedingung"}  # fmt: skip
# Words that identify a component type when no explicit ID is given, checked in this order
# ("hydrogen recirculation blower" must resolve before the generic "blower").
TYPE_WORDS = {
    "h2_recirculation": ("recirculation", "rezirkulation"),
    "air_compressor": ("compressor", "verdichter"),
    "air_blower": ("blower", "gebläse"),
    "humidifier": ("humidifier", "befeuchter"),
    "coolant_pump": ("coolant pump", "kühlmittelpumpe"),
    "stack": ("stack", "electrical characteristics", "elektrische kennwerte",
              "materials and catalyst", "werkstoffe"),
}  # fmt: skip


def normalise_label(text: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", text.lower()).strip()


@dataclass
class Vocabulary:
    labels: dict[str, str] = field(default_factory=dict)
    """Normalised label to canonical key."""
    canonical_units: dict[str, str] = field(default_factory=dict)
    key_components: dict[str, set[str | None]] = field(default_factory=dict)
    """Key to the component types that define it (None means system level)."""
    systems: dict[str, SystemTruth] = field(default_factory=dict)

    @classmethod
    def from_truth(cls, systems_dir: Path, synonyms: Path | None = None) -> "Vocabulary":
        vocab = cls(systems={s.system: s for s in load_all(systems_dir).values()})
        for system in vocab.systems.values():
            entries = [(None, p) for p in system.parameters] + [
                (c.type, p) for c in system.components for p in c.parameters
            ]
            for ctype, p in entries:
                vocab.labels[normalise_label(p.label_en)] = p.key
                vocab.labels[normalise_label(p.label_de)] = p.key
                vocab.canonical_units[p.key] = p.unit
                vocab.key_components.setdefault(p.key, set()).add(ctype)
        if synonyms is not None and synonyms.exists():
            data = yaml.safe_load(synonyms.read_text(encoding="utf-8")) or {}
            for key, words in (data.get("synonyms") or {}).items():
                for word in words:
                    vocab.labels[normalise_label(word)] = key
        return vocab

    def key_for(self, label: str) -> str | None:
        return self.labels.get(normalise_label(label))

    def resolve_component(self, system: str, key: str, context: Iterable[str]) -> str | None:
        """Component ID from an explicit ID in the context, the key itself, or heading words."""
        truth = self.systems.get(system)
        if truth is None:
            return None
        text = " ".join(context)
        explicit = COMPONENT_ID.search(text)
        if explicit and explicit.group(1) == truth.code:
            return explicit.group(0)
        types = self.key_components.get(key, set())
        if types == {None}:
            return None
        if len(types) == 1:
            (ctype,) = types
            return next((c.id for c in truth.components if c.type == ctype), None)
        lowered = text.lower()
        for ctype, words in TYPE_WORDS.items():
            if ctype in types and any(w in lowered for w in words):
                return next((c.id for c in truth.components if c.type == ctype), None)
        return None


def _record(
    vocab: Vocabulary, sf: SourceFile, key: str, label: str, value: float, unit: str | None,
    condition: str | None, context: list[str], locator: dict[str, Any], method: str, text: str,
) -> Parameter | None:  # fmt: skip
    assert sf.system is not None
    canonical = vocab.canonical_units.get(key)
    if canonical is None:
        return None
    unit = unit or "-"
    normalised = convert_value(value, unit, canonical)
    if normalised is None:  # wrong dimension: not this parameter
        return None
    return Parameter(
        system=sf.system,
        component=vocab.resolve_component(sf.system, key, context),
        parameter=key,
        label=label,
        value=value,
        unit=unit,
        value_norm=round(normalised, 6),
        unit_norm=canonical,
        condition=condition or None,
        doc_id=sf.doc_id,
        doc_version=sf.doc_version,
        locator=locator,
        method=method,
        source_text=text[:500],
    )


def _from_row(vocab: Vocabulary, sf: SourceFile, el: Element, language: str) -> Parameter | None:
    data = el.data or {}
    context = [data.get("caption", ""), *el.heading_path]
    if "parameter" in data:  # wide layout: one parameter per column
        label, raw, unit_text, condition = data["parameter"], data["value"], data["unit"], None
    else:
        columns = [normalise_label(c) for c in data.get("columns", [])]
        values = dict(zip(columns, data.get("values", []), strict=False))

        def pick(names: set[str]) -> str:
            return next((values[c] for c in columns if c in {normalise_label(n) for n in names}
                         and values.get(c)), "")  # fmt: skip

        label, raw = pick(NAME_COLUMNS), pick(VALUE_COLUMNS)
        unit_text, condition = pick(UNIT_COLUMNS), pick(CONDITION_COLUMNS)
    key = vocab.key_for(label) if label else None
    if key is None or not raw:
        return None
    unit = to_pint(unit_text)
    if unit is None:
        return None
    try:
        value = parse_number(str(raw), language)
    except ValueError:
        return None
    return _record(vocab, sf, key, label, value, unit, condition, context, el.locator, "table",
                   el.content)  # fmt: skip


SENTENCE = re.compile(r"(?<=[.;])\s+")


def _from_prose(
    vocab: Vocabulary, sf: SourceFile, el: Element, language: str, method: str
) -> list[Parameter]:
    text = (el.data or {}).get("text") or el.content
    records = []
    for sentence in SENTENCE.split(text):
        norm = normalise_label(sentence)
        # Longest label first, so "maximum coolant outlet temperature" beats "coolant outlet".
        for label_norm, key in sorted(vocab.labels.items(), key=lambda kv: -len(kv[0])):
            if len(label_norm) < 8 or label_norm not in norm:
                continue
            start = sentence.lower().find(label_norm.split(" ")[-1])
            tail = sentence[max(start, 0) :]
            quantity = next(iter(extract_quantities(tail, language)), None)
            if quantity is None:
                break
            condition = m.group(1) if (m := re.search(r"\(([^)]*)\)", tail)) else None
            context = [*el.heading_path, sentence, (el.data or {}).get("title", "")]
            record = _record(vocab, sf, key, label_norm, quantity.value, quantity.unit, condition,
                             context, el.locator, method, sentence)  # fmt: skip
            if record:
                records.append(record)
            break
    return records


def extract_parameters(
    vocab: Vocabulary, sf: SourceFile, elements: list[Element]
) -> list[Parameter]:
    """Records for the fictional systems; documents without a system tag are skipped."""
    if sf.system is None or sf.system not in vocab.systems:
        return []
    language = sf.language or "en"
    records: list[Parameter] = []
    for el in elements:
        if el.kind == "table_row":
            record = _from_row(vocab, sf, el, language)
            if record:
                records.append(record)
        elif el.kind == "text":
            records += _from_prose(vocab, sf, el, language, "prose")
        elif el.kind == "requirement":
            records += _from_prose(vocab, sf, el, language, "requirement")
    return records
