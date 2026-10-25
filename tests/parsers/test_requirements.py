"""Requirements parser against the three generated export formats."""

from pathlib import Path

import pytest

from fcrag.datagen import requirements as gen
from fcrag.ingest.parsers.requirements import RequirementsParser, parse_csv
from fcrag.models import Element, SourceFile
from fcrag.truth import SystemTruth


def parse(path: Path) -> list[Element]:
    sf = SourceFile(path=path, sha256="0" * 64, mime_type="x", doc_id=path.stem)
    return list(RequirementsParser().parse(sf))


@pytest.mark.parametrize("code", ["A", "B", "C"])
def test_round_trip(systems: dict[str, SystemTruth], tmp_path: Path, code: str) -> None:
    generated = gen.WRITERS[code](systems[code], tmp_path)
    expected = gen.build_requirements(systems[code], generated.language)
    elements = parse(tmp_path / generated.file)

    by_id = {e.locator["req_id"]: e for e in elements}
    assert list(by_id) == [r.req_id for r in expected]
    for req in expected:
        data = by_id[req.req_id].data
        assert data is not None
        assert data["text"] == req.text
        assert data["parent"] == req.parent
        assert data["status"] == req.status
        assert data["verification"] == req.verification
    assert {f.locator["req_id"] for f in generated.facts} <= set(by_id)


def test_parent_context_and_prose_links(systems: dict[str, SystemTruth], tmp_path: Path) -> None:
    generated = gen.write_reqif(systems["A"], tmp_path)
    elements = parse(tmp_path / generated.file)
    child = next(e for e in elements if e.data and e.data["parent"])
    assert f"Parent {child.data['parent']}" in child.content  # type: ignore[index]
    linked = next(e for e in elements if "See also" in e.content)
    assert linked.data is not None and linked.data["links"]


def test_conflicting_requirement_is_present(
    systems: dict[str, SystemTruth], tmp_path: Path
) -> None:
    generated = gen.write_reqif(systems["A"], tmp_path)
    conflict = next(
        f for f in generated.facts if f.key == "coolant_outlet_temperature_max" and f.component
    )
    assert conflict.stated_value == 90.0 != conflict.truth_value


def test_csv_variants() -> None:
    reqs = parse_csv("Requirement ID,Description,Status\nSR-001,Shall purge,approved\n,,\n")
    assert [(r.req_id, r.text, r.status) for r in reqs] == [("SR-001", "Shall purge", "approved")]
    with pytest.raises(ValueError, match="no requirement ID"):
        parse_csv("a;b\n1;2\n")
