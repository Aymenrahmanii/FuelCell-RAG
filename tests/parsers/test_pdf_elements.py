"""Docling document to elements: heading paths, skipped headers/footers, tables and row facts."""

from typing import Any

import pytest

from fcrag.ingest.parsers.pdf import document_elements, heading_level

dl = pytest.importorskip("docling_core.types.doc")


def prov(page: int) -> Any:
    return dl.ProvenanceItem(
        page_no=page,
        # PDF coordinates, as Docling's PDF backend reports them
        bbox=dl.BoundingBox(l=50, t=700, r=500, b=650, coord_origin=dl.CoordOrigin.BOTTOMLEFT),
        charspan=(0, 1),
    )


def build_doc() -> Any:
    doc = dl.DoclingDocument(name="datasheet")
    doc.add_page(page_no=1, size=dl.Size(width=595, height=842))
    doc.add_page(page_no=2, size=dl.Size(width=595, height=842))
    doc.add_title(text="Stack Datasheet B", prov=prov(1))
    doc.add_text(label=dl.DocItemLabel.PAGE_HEADER, text="CONFIDENTIAL draft", prov=prov(1))
    doc.add_heading(text="3 Operating limits", level=1, prov=prov(1))
    doc.add_heading(text="3.2 Temperatures", level=1, prov=prov(1))
    doc.add_text(label=dl.DocItemLabel.TEXT, text="Coolant outlet max 85 °C.", prov=prov(1))
    doc.add_heading(text="4 Materials", level=1, prov=prov(2))
    cells = [
        dl.TableCell(text=text, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                     start_col_offset_idx=c, end_col_offset_idx=c + 1, column_header=r == 0)
        for r, row in enumerate([["Part", "Material"], ["Plate", "Graphite"], ["Seal", "EPDM"]])
        for c, text in enumerate(row)
    ]  # fmt: skip
    doc.add_table(data=dl.TableData(num_rows=3, num_cols=2, table_cells=cells), prov=prov(2))
    doc.add_text(label=dl.DocItemLabel.PAGE_FOOTER, text="Page 2 of 2", prov=prov(2))
    return doc


def test_heading_level_prefers_section_numbers() -> None:
    assert heading_level("3.2.1 Coolant", fallback=1) == 3
    assert heading_level("4. Materials", fallback=1) == 1
    assert heading_level("Introduction", fallback=2) == 2


def test_elements_carry_heading_path_and_skip_page_furniture() -> None:
    elements = list(document_elements(build_doc()))
    assert not any("CONFIDENTIAL" in e.content or "Page 2" in e.content for e in elements)

    text = next(e for e in elements if e.kind == "text")
    assert text.heading_path == ["Stack Datasheet B", "3 Operating limits", "3.2 Temperatures"]
    assert text.locator["page"] == 1
    assert text.locator["bbox"] == [50.0, 142.0, 500.0, 192.0]  # converted to top-left origin


def test_tables_become_table_and_row_facts() -> None:
    elements = list(document_elements(build_doc()))
    table = next(e for e in elements if e.kind == "table")
    assert table.heading_path == ["Stack Datasheet B", "4 Materials"]
    assert table.data is not None and table.data["columns"] == ["Part", "Material"]
    rows = [e.content for e in elements if e.kind == "table_row"]
    assert rows == [
        "4 Materials | Part: Plate | Material: Graphite",
        "4 Materials | Part: Seal | Material: EPDM",
    ]
    assert [e.locator["row"] for e in elements if e.kind == "table_row"] == [1, 2]
