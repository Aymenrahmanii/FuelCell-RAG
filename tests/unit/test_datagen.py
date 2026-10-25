"""Generated corpus: complete, versioned, and every fact points back at the truth."""

import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from fcrag.datagen.common import convert, format_number, value_at_version
from fcrag.datagen.run import generate
from fcrag.truth import SystemTruth


@pytest.fixture(scope="module")
def corpus(repo_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("generated")
    generate(repo_root / "data_gen" / "systems", out)
    return out


def test_manifest_lists_every_file(corpus: Path) -> None:
    manifest = yaml.safe_load((corpus / "manifest.yaml").read_text(encoding="utf-8"))
    files = {e["file"] for e in manifest["files"]}
    on_disk = {p.name for p in corpus.iterdir()} - {"manifest.yaml", "facts.jsonl"}
    assert files == on_disk
    doc_types = {e["doc_type"] for e in manifest["files"]}
    # STEP files ("cad") need the optional CadQuery extra
    assert {"datasheet", "parameter_sheet", "requirements"} <= doc_types
    assert doc_types <= {"datasheet", "parameter_sheet", "requirements", "cad"}
    assert all(e["licence"].startswith("Synthetic") for e in manifest["files"])


def test_datasheets_state_every_parameter_once_per_version(
    corpus: Path, systems: dict[str, SystemTruth]
) -> None:
    facts = [json.loads(line) for line in (corpus / "facts.jsonl").open(encoding="utf-8")]
    for system in systems.values():
        expected = {(None, p.key) for p in system.parameters} | {
            (c.id, p.key) for c in system.components for p in c.parameters
        }
        for version in (1, 2):
            stated = [
                (f["component"], f["key"])
                for f in facts
                if f["doc_id"] == f"ds-system-{system.code.lower()}" and f["doc_version"] == version
            ]
            assert Counter(stated) == Counter(expected), (system.code, version)


def test_old_versions_show_superseded_values(corpus: Path) -> None:
    facts = [json.loads(line) for line in (corpus / "facts.jsonl").open(encoding="utf-8")]
    humidifier = {
        (f["doc_id"], f["doc_version"]): f["stated_value"]
        for f in facts
        if f["key"] == "pressure_drop_dry_side" and f["component"] == "A-HUM"
    }
    assert humidifier[("ds-system-a", 1)] == 18
    assert humidifier[("ds-system-a", 2)] == 15
    assert humidifier[("ps-system-a", 2)] == 15


def test_unit_variants_are_exact_conversions(corpus: Path) -> None:
    facts = [json.loads(line) for line in (corpus / "facts.jsonl").open(encoding="utf-8")]
    variants = [f for f in facts if f["stated_unit"] != f["truth_unit"]]
    assert {(f["truth_unit"], f["stated_unit"]) for f in variants} == {
        ("kPa", "bar"), ("degC", "K"), ("kW", "W"),
    }  # fmt: skip
    for f in variants:
        assert f["stated_value"] == convert(f["truth_value"], f["truth_unit"], f["stated_unit"])


def test_conflicting_requirements_are_the_only_mismatches(corpus: Path) -> None:
    facts = [json.loads(line) for line in (corpus / "facts.jsonl").open(encoding="utf-8")]
    same_unit = [f for f in facts if f["stated_unit"] == f["truth_unit"]]
    mismatches = {
        (f["doc_id"], f["key"]) for f in same_unit if f["stated_value"] != f["truth_value"]
    }
    assert mismatches == {
        ("req-system-a", "coolant_outlet_temperature_max"),
        ("req-system-b", "cathode_inlet_pressure_rated"),
        ("req-system-c", "coolant_flow_rated"),
    }


def test_formatting_helpers(systems: dict[str, SystemTruth]) -> None:
    assert format_number(25000, "de") == "25.000"
    assert format_number(0.25, "de") == "0,25"
    assert format_number(25000.5, "en") == "25,000.5"
    lifetime = systems["B"].lookup("design_lifetime")
    assert value_at_version(lifetime, 1) == 20000
    assert value_at_version(lifetime, 2) == 25000
