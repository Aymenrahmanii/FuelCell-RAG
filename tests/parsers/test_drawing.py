"""Drawing parsing on the generated schematics: text layer, OCR path, routing, vision model."""

import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fcrag.config import Settings
from fcrag.datagen import drawing as gen
from fcrag.ingest.parsers import drawing, parser_for
from fcrag.ingest.parsers.pdf import PdfParser
from fcrag.models import Element, SourceFile
from fcrag.truth import SystemTruth


def _render(systems: dict[str, SystemTruth], code: str, out: Path, version: int = -1) -> Path:
    spec = gen.DRAWINGS[code][version]
    path = out / f"{spec.doc_id}_v{spec.version}.pdf"
    gen.render_pdf(systems[code], spec, path)
    return path


def _source(path: Path, language: str = "en") -> SourceFile:
    return SourceFile(
        path=path, sha256="0" * 64, mime_type="application/pdf", doc_id=path.stem,
        doc_type="drawing", language=language,
    )  # fmt: skip


def _parse(sf: SourceFile) -> list[Element]:
    return list(drawing.DrawingParser().parse(sf))


def _expected(
    system: SystemTruth, spec: gen.Drawing
) -> tuple[dict[str, str], list[dict[str, str]]]:
    de = spec.language == "de"
    names = {f"{system.code}-{s.suffix}": s.name_de if de else s.name_en
             for s in gen.symbols(system, spec)}  # fmt: skip
    lines = [
        {"line": ln.line_id, "medium": ln.medium_de if de else ln.medium_en,
         "from": f"{system.code}-{ln.source}", "to": f"{system.code}-{ln.target}"}
        for ln in gen.lines(system, spec)
    ]  # fmt: skip
    return names, lines


@pytest.mark.parametrize(("code", "version"), [("A", 0), ("A", 1), ("B", 0)])
def test_text_layer_reads_the_whole_sheet(
    systems: dict[str, SystemTruth], tmp_path: Path, code: str, version: int
) -> None:
    spec = gen.DRAWINGS[code][version]
    summary, block = _parse(_source(_render(systems, code, tmp_path, version), spec.language))
    names, lines = _expected(systems[code], spec)
    assert summary.data is not None and summary.data["text_source"] == "pdf"
    assert {c["tag"]: c["name"] for c in summary.data["components"]} == names
    assert summary.data["lines"] == lines
    assert summary.data["title_block"]["drawing_no"] == spec.drawing_no
    assert summary.data["title_block"]["revision"] == spec.revision
    assert [r["rev"] for r in summary.data["revisions"]] == [r.rev for r in spec.revisions]
    assert summary.locator == {"page": 1, "drawing_no": spec.drawing_no, "revision": spec.revision}
    assert block.locator == summary.locator


def test_element_text(systems: dict[str, SystemTruth], tmp_path: Path) -> None:
    summary, block = _parse(_source(_render(systems, "A", tmp_path)))
    assert summary.content.startswith(
        "Drawing DWG-A-0001 rev B, sheet 1/1: System A – fuel cell system schematic."
    )
    assert (
        "- L14 Air from A-CMP (Electric turbo air compressor) to A-BPV (Humidifier bypass valve)"
        in summary.content
    )
    assert "Notes: Schematic, not to scale." in summary.content
    assert summary.heading_path == ["DWG-A-0001"]
    assert "Revision: B" in block.content
    assert "- rev B (2026-07-14, FC-Design): Humidifier bypass valve A-BPV added" in block.content


def test_german_element_text(systems: dict[str, SystemTruth], tmp_path: Path) -> None:
    summary, block = _parse(_source(_render(systems, "B", tmp_path), "de"))
    assert summary.content.startswith("Zeichnung DWG-B-0001 Index A, Blatt 1/1:")
    assert (
        "- L02 Luft von B-CMP (Elektrischer Turboverdichter (je Modul)) nach B-HUM"
        in summary.content
    )
    assert block.content.startswith("Schriftfeld der Zeichnung DWG-B-0001: Benennung:")


def test_hidden_labels_are_not_names(systems: dict[str, SystemTruth], tmp_path: Path) -> None:
    """Line L03 runs under the bypass valve; its label is covered but still in the text layer."""
    summary, _ = _parse(_source(_render(systems, "A", tmp_path)))
    assert summary.data is not None
    names = {c["tag"]: c["name"] for c in summary.data["components"]}
    assert names["A-BPV"] == "Humidifier bypass valve"


def test_image_goes_through_ocr(
    systems: dict[str, SystemTruth], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The raster path, with OCR replaced by the vector text scaled to pixels and shuffled."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(_render(systems, "C", tmp_path)))
    vector = drawing.pdf_segments(pdf[0])
    pdf.close()
    scale = gen.RASTER_DPI / 72
    boxes = [drawing.Segment(s.text.strip(), s.x0 * scale, s.y0 * scale, s.x1 * scale,
                             s.y1 * scale) for s in vector]  # fmt: skip
    random.Random(0).shuffle(boxes)
    monkeypatch.setattr(drawing, "ocr_segments", lambda image: boxes)

    out = gen.build_drawing(systems["C"], gen.DRAWINGS["C"][0], tmp_path)
    assert out.file.endswith(".png") and not (tmp_path / "dwg-schematic-c.pdf").exists()
    sf = SourceFile(
        path=tmp_path / out.file, sha256="0" * 64, mime_type="image/png", doc_id=out.doc_id,
        doc_type="drawing", language="en",
    )  # fmt: skip
    assert isinstance(parser_for(sf), drawing.DrawingParser)
    summary, _ = _parse(sf)
    names, lines = _expected(systems["C"], gen.DRAWINGS["C"][0])
    assert summary.data is not None and summary.data["text_source"] == "ocr"
    assert {c["tag"]: c["name"] for c in summary.data["components"]} == names
    assert summary.data["lines"] == lines


def test_real_ocr(systems: dict[str, SystemTruth], tmp_path: Path) -> None:
    pytest.importorskip("rapidocr")
    out = gen.build_drawing(systems["C"], gen.DRAWINGS["C"][0], tmp_path)
    sf = SourceFile(
        path=tmp_path / out.file, sha256="0" * 64, mime_type="image/png", doc_id=out.doc_id,
        doc_type="drawing", language="en",
    )  # fmt: skip
    summary, _ = _parse(sf)
    _, lines = _expected(systems["C"], gen.DRAWINGS["C"][0])
    assert summary.data is not None and summary.data["lines"] == lines


def test_drawing_pdfs_route_by_doc_type(tmp_path: Path) -> None:
    path = tmp_path / "x.pdf"
    report = SourceFile(path=path, sha256="0" * 64, mime_type="application/pdf", doc_id="x")
    assert isinstance(parser_for(report), PdfParser)
    assert isinstance(parser_for(_source(path)), drawing.DrawingParser)


def test_sheet_without_structure_keeps_its_text() -> None:
    """A public diagram with no line list or title block: all text is kept for search."""
    segments = [
        drawing.Segment("Cathode subsystem", 10, 10, 90, 18),
        drawing.Segment("Air filter", 10, 40, 50, 48),
        drawing.Segment("Compressor", 70, 40, 120, 48),
    ]
    sheet = drawing.analyse(segments)
    assert drawing._describe(sheet, "en") == (
        "",
        "Text on the drawing: Cathode subsystem Air filter Compressor",
    )


def _settings(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_vision_model_description_is_marked(
    systems: dict[str, SystemTruth], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import litellm

    calls: list[dict[str, Any]] = []
    text = "Air enters through A-AIR and is compressed by A-CMP."

    def completion(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(drawing, "get_settings", lambda: _settings(drawing_vlm=True))
    elements = _parse(_source(_render(systems, "A", tmp_path)))
    assert len(elements) == 3
    vlm = elements[2]
    assert vlm.data == {"confidence": "low", "model": "gemini/gemini-3.5-flash"}
    assert vlm.locator["source"] == "vision_model"
    assert vlm.content.startswith("Vision model description of drawing DWG-A-0001 (unverified")
    image = calls[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/png;base64,")

    from fcrag.ingest.chunking import ChunkingConfig, build_chunks

    chunks = build_chunks(elements, _source(tmp_path / "x.pdf"), ChunkingConfig(), is_latest=True)
    assert [c.meta for c in chunks] == [{}, {}, {"confidence": "low"}]


def test_restricted_mode_never_sends_drawings_out(
    systems: dict[str, SystemTruth], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import litellm

    def completion(**kwargs: Any) -> None:
        raise AssertionError("no hosted call in restricted mode")

    monkeypatch.setattr(litellm, "completion", completion)
    restricted = _settings(drawing_vlm=True, restricted_mode=True)
    monkeypatch.setattr(drawing, "get_settings", lambda: restricted)
    assert len(_parse(_source(_render(systems, "A", tmp_path)))) == 2
