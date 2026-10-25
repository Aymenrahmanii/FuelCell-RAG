"""STEP parsing: text fallback (always) and full geometry on generated files (with CadQuery)."""

from pathlib import Path

import pytest

from fcrag.ingest.parsers.step import StepParser, tree_from_text
from fcrag.models import SourceFile
from fcrag.truth import SystemTruth

# Minimal AP214 structure: an assembly "EPA-01" with two parts.
MINI_STEP = """ISO-10303-21;
HEADER;
ENDSEC;
DATA;
#1 = PRODUCT('EPA-01','EPA-01','',(#9));
#2 = PRODUCT_DEFINITION_FORMATION('','',#1);
#3 = PRODUCT_DEFINITION('design','',#2,#10);
#4 = PRODUCT('EP-01','EP-01','',(#9));
#5 = PRODUCT_DEFINITION_FORMATION('','',#4);
#6 = PRODUCT_DEFINITION('design','',#5,#10);
#7 = PRODUCT('CC-01','CC-01','',(#9));
#8 = PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#7,
  .NOT_KNOWN.);
#11 = PRODUCT_DEFINITION('design','',#8,#10);
#12 = NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','EP-01','',#3,#6,$);
#13 = NEXT_ASSEMBLY_USAGE_OCCURRENCE('2','CC-01','',#3,#11,$);
ENDSEC;
END-ISO-10303-21;
"""


def test_tree_from_text() -> None:
    (root,) = tree_from_text(MINI_STEP)
    assert root.name == "EPA-01"
    assert [c.name for c in root.children] == ["EP-01", "CC-01"]


def test_text_fallback_elements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcrag.ingest.parsers.step as step

    def no_cad(_: Path) -> list[step.Node]:
        raise ImportError

    monkeypatch.setattr(step, "tree_from_cad", no_cad)
    path = tmp_path / "mini.step"
    path.write_text(MINI_STEP, encoding="utf-8")
    sf = SourceFile(path=path, sha256="0" * 64, mime_type="model/step", doc_id="cad")
    elements = list(StepParser().parse(sf))
    assert elements[0].content.startswith("STEP assembly EPA-01: 2 parts.")
    assert [e.locator["part_id"] for e in elements] == ["EPA-01", "EP-01", "CC-01"]
    assert elements[1].data is not None and elements[1].data["parent"] == "EPA-01"


def test_generated_assembly_with_geometry(systems: dict[str, SystemTruth], tmp_path: Path) -> None:
    pytest.importorskip("cadquery")
    from fcrag.datagen.cad import CELL_PITCH_MM, build_step

    generated = build_step(systems["B"], tmp_path)
    sf = SourceFile(path=tmp_path / generated.file, sha256="0" * 64, mime_type="x", doc_id="c")
    elements = {e.locator["part_id"]: e for e in StepParser().parse(sf)}
    assert "EPA-02 -> EP-02, INS-02, CC-02" in elements["B-STK-ASM"].content
    block = elements["CB-01"].data
    assert block is not None
    assert block["size_mm"][2] == pytest.approx(440 * CELL_PITCH_MM["B"], abs=0.1)
    assert elements["EP-02"].data is not None and elements["EP-02"].data["parent"] == "EPA-02"
