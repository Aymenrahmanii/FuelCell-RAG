"""Shared helpers: number and unit formatting per language, unit variants, fact records."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from fcrag.truth import Component, SystemTruth, TruthParameter, parse_unit, ureg

LICENCE = "Synthetic, generated from data_gen/systems (no third-party content)"


def format_number(value: float, language: str) -> str:
    """At most four significant decimals, no trailing zeros; German uses decimal commas."""
    if float(value).is_integer():
        text = f"{int(value):,}"
    else:
        text = f"{value:,.4f}".rstrip("0").rstrip(".")
    if language == "de":
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text


def convert(value: float, unit: str, target: str) -> float:
    """Convert a truth value into a variant unit (kPa to bar, °C to K, ...), rounded sensibly."""
    quantity = ureg.Quantity(value, parse_unit(unit)).to(parse_unit(target))
    return round(float(quantity.magnitude), 4)


def label(param: TruthParameter, language: str) -> str:
    return param.label_de if language == "de" else param.label_en


def value_at_version(param: TruthParameter, doc_version: int) -> float:
    """The value a document of ``doc_version`` states: older versions show superseded values."""
    for revision in sorted(param.superseded, key=lambda r: r.doc_version):
        if doc_version <= revision.doc_version:
            return revision.value
    return param.value


def doc_versions(system: SystemTruth) -> int:
    """Number of document versions needed so every superseded value appears once."""
    params = list(system.parameters) + [p for c in system.components for p in c.parameters]
    return max(p.current_doc_version for p in params)


@dataclass
class Fact:
    """One truth value as stated in one generated document."""

    system: str
    component: str | None
    key: str
    truth_value: float
    truth_unit: str
    stated_value: float
    stated_unit: str
    doc_id: str
    doc_version: int
    locator: dict[str, Any]


@dataclass
class GeneratedFile:
    file: str
    doc_id: str
    doc_version: int
    title: str
    system: str
    doc_type: str
    language: str
    licence: str = LICENCE
    facts: list[Fact] = field(default_factory=list)

    def manifest_entry(self) -> dict[str, Any]:
        entry = asdict(self)
        entry.pop("facts")
        return entry


def make_fact(
    system: SystemTruth,
    component: Component | None,
    param: TruthParameter,
    stated_value: float,
    stated_unit: str,
    out: GeneratedFile,
    locator: dict[str, Any],
    *,
    truth_value: float | None = None,
) -> Fact:
    """``truth_value`` defaults to what a document of ``out.doc_version`` should state."""
    return Fact(
        system=system.system,
        component=component.id if component else None,
        key=param.key,
        truth_value=value_at_version(param, out.doc_version)
        if truth_value is None
        else truth_value,
        truth_unit=param.unit,
        stated_value=stated_value,
        stated_unit=stated_unit,
        doc_id=out.doc_id,
        doc_version=out.doc_version,
        locator=locator,
    )


def write_manifest(out_dir: Path, files: list[GeneratedFile]) -> None:
    manifest = {"files": [f.manifest_entry() for f in files]}
    (out_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    with (out_dir / "facts.jsonl").open("w", encoding="utf-8") as f:
        for generated in files:
            for fact in generated.facts:
                f.write(json.dumps(asdict(fact), ensure_ascii=False) + "\n")
