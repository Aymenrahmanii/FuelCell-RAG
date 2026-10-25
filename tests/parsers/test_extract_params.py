"""Parameter extraction scored against the generator's facts (Excel and requirements files)."""

from pathlib import Path

import pytest
import yaml

from fcrag.datagen.common import Fact
from fcrag.datagen.run import generate
from fcrag.ingest.extract_params import Vocabulary, extract_parameters
from fcrag.ingest.parsers.excel import ExcelParser
from fcrag.ingest.parsers.requirements import RequirementsParser
from fcrag.models import Parameter, Parser, SourceFile
from fcrag.units import convert_value

PARSERS: dict[str, Parser] = {
    ".xlsx": ExcelParser(),
    ".reqif": RequirementsParser(),
    ".docx": RequirementsParser(),
    ".csv": RequirementsParser(),
}


@pytest.fixture(scope="module")
def extracted(
    repo_root: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[list[Fact], list[Parameter]]:
    out = tmp_path_factory.mktemp("gen")
    files = generate(repo_root / "data_gen/systems", out)
    vocab = Vocabulary.from_truth(
        repo_root / "data_gen/systems", repo_root / "data_gen/synonyms.yaml"
    )
    manifest = {
        e["file"]: e for e in yaml.safe_load((out / "manifest.yaml").read_text("utf-8"))["files"]
    }
    facts: list[Fact] = []
    records: list[Parameter] = []
    for generated in files:
        path = out / generated.file
        if path.suffix not in PARSERS:
            continue
        meta = manifest[generated.file]
        sf = SourceFile(
            path=path, sha256="0" * 64, mime_type="x", doc_id=meta["doc_id"],
            doc_version=meta["doc_version"], system=meta["system"], language=meta["language"],
        )  # fmt: skip
        records += extract_parameters(vocab, sf, list(PARSERS[path.suffix].parse(sf)))
        facts += generated.facts
    return facts, records


def _stated_norm(fact: Fact) -> float:
    value = convert_value(fact.stated_value, fact.stated_unit, fact.truth_unit)
    assert value is not None
    return value


def _same(fact: Fact, record: Parameter) -> bool:
    return (
        record.doc_id == fact.doc_id and record.doc_version == fact.doc_version
        and record.parameter == fact.key and record.component == fact.component
        and abs(record.value_norm - _stated_norm(fact)) <= 1e-6 * max(1, abs(_stated_norm(fact)))
    )  # fmt: skip


def test_recall_and_precision(extracted: tuple[list[Fact], list[Parameter]]) -> None:
    facts, records = extracted
    found = [f for f in facts if any(_same(f, r) for r in records)]
    correct = [r for r in records if any(_same(f, r) for f in facts)]
    missed = [(f.doc_id, f.component, f.key) for f in facts if f not in found][:10]
    wrong = [(r.doc_id, r.component, r.parameter, r.value) for r in records if r not in correct][
        :10
    ]
    assert len(found) / len(facts) >= 0.95, missed
    assert len(correct) / len(records) >= 0.98, wrong


def test_units_are_normalised(extracted: tuple[list[Fact], list[Parameter]]) -> None:
    _, records = extracted
    kelvin = next(r for r in records if r.unit == "K" and r.parameter.endswith("temperature_max"))
    assert kelvin.unit_norm == "degC"
    assert kelvin.value_norm == pytest.approx(kelvin.value - 273.15)
    watts = next(r for r in records if r.unit == "W")
    assert watts.value_norm == pytest.approx(watts.value / 1000)


def test_conflicting_requirement_is_extracted_as_stated(
    extracted: tuple[list[Fact], list[Parameter]],
) -> None:
    _, records = extracted
    conflict = next(
        r for r in records
        if r.doc_id == "req-system-a" and r.parameter == "coolant_outlet_temperature_max"
        and r.component == "A-STK"
    )  # fmt: skip
    assert conflict.value_norm == 90
    assert conflict.method == "requirement"
    assert conflict.locator["req_id"].startswith("REQ-A-")
