"""Parser snapshot tests: every golden input must parse to exactly its committed elements.

Inputs are the generated corpus (deterministic, rebuilt here, so no binaries are committed)
plus hand-written files in ``golden/inputs/``. Expected outputs live in ``golden/<name>.json``.
After an intended parser or generator change, review the diff and update them with:

    FCRAG_UPDATE_GOLDEN=1 uv run pytest tests/parsers/test_golden.py
"""

import json
import os
from pathlib import Path

import pytest

import fcrag.ingest.pipeline  # noqa: F401  (registers the parsers)
from fcrag.datagen.run import generate
from fcrag.ingest.discover import discover, sha256_file
from fcrag.ingest.parsers import parser_for
from fcrag.models import SourceFile

GOLDEN = Path(__file__).parent / "golden"
UPDATE = os.environ.get("FCRAG_UPDATE_GOLDEN") == "1"

GENERATED = [
    # Excel: merged headers, two-row headers, units rows, hidden rows, wide layout, BOM
    "ps-system-a_v1.xlsx", "ps-system-a_v2.xlsx", "ps-system-b_v1.xlsx", "ps-system-b_v2.xlsx",
    "ps-system-c_v1.xlsx", "ps-system-c_v2.xlsx",
    # Requirements: ReqIF, DOCX numbering, CSV
    "req-system-a.reqif", "req-system-b.docx", "req-system-c.csv",
    # Drawings (text layer): system schematics in two revisions and German, subsystem sheets
    "dwg-schematic-a_v1.pdf", "dwg-schematic-a_v2.pdf", "dwg-schematic-b.pdf",
    "dwg-air-a.pdf", "dwg-air-b.pdf", "dwg-air-c.pdf", "dwg-anode-a.pdf", "dwg-anode-b.pdf",
    "dwg-anode-c.pdf", "dwg-coolant-a.pdf", "dwg-coolant-b.pdf", "dwg-coolant-c.pdf",
]  # fmt: skip
HANDWRITTEN = ["end-plate-assembly.step"]


@pytest.fixture(scope="module")
def generated(repo_root: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, SourceFile]:
    out = tmp_path_factory.mktemp("corpus")
    generate(repo_root / "data_gen" / "systems", out)
    return {sf.path.name: sf for sf in discover([out], repo_root / "data/sources.yaml")}


def _snapshot(sf: SourceFile) -> list[dict[str, object]]:
    return [e.model_dump(mode="json") for e in parser_for(sf).parse(sf)]


def _check(name: str, actual: list[dict[str, object]]) -> None:
    path = GOLDEN / f"{name}.json"
    if UPDATE:
        path.write_text(json.dumps(actual, indent=1, ensure_ascii=False) + "\n", "utf-8")
    assert path.exists(), f"no golden file for {name}: run with FCRAG_UPDATE_GOLDEN=1"
    expected = json.loads(path.read_text("utf-8"))
    assert len(actual) == len(expected), f"{name}: element count changed"
    for n, (got, want) in enumerate(zip(actual, expected, strict=True)):
        assert got == want, f"{name}: element {n} differs"


@pytest.mark.parametrize("name", GENERATED)
def test_generated_file_parses_to_its_snapshot(generated: dict[str, SourceFile], name: str) -> None:
    _check(name, _snapshot(generated[name]))


@pytest.mark.parametrize("name", HANDWRITTEN)
def test_handwritten_file_parses_to_its_snapshot(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fcrag.ingest.parsers.step as step

    def no_cad(_: Path) -> list[step.Node]:
        raise ImportError  # the text fallback, identical with or without CadQuery installed

    monkeypatch.setattr(step, "tree_from_cad", no_cad)
    path = GOLDEN / "inputs" / name
    sf = SourceFile(path=path, sha256=sha256_file(path), mime_type="model/step", doc_id=path.stem)
    _check(name, _snapshot(sf))


def test_every_golden_file_has_a_test() -> None:
    """A snapshot whose input was removed would otherwise go stale silently."""
    files = {p.name.removesuffix(".json") for p in GOLDEN.glob("*.json")}
    assert files == set(GENERATED) | set(HANDWRITTEN)
