"""PDF parser: Docling layout analysis (reading order, headings, TableFormer tables).

Docling is imported lazily, so the rest of the package works without the ``ml`` extra.
"""

import gc
import re
import sys
from collections.abc import Iterator
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from fcrag.config import get_settings
from fcrag.ingest.parsers import register
from fcrag.models import Element, SourceFile

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc import DoclingDocument

SKIP_LABELS = {"page_header", "page_footer"}
NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
MAX_ROW_FACTS = 200


def heading_level(text: str, fallback: int) -> int:
    """Docling reports most headings as level 1; numbers ("3.2 Limits") are more reliable."""
    match = NUMBERED_HEADING.match(text)
    return len(match.group(1).split(".")) if match else max(fallback, 1)


def _locator(item: Any, doc: "DoclingDocument") -> dict[str, Any]:
    if not item.prov:
        return {}
    prov = item.prov[0]
    locator: dict[str, Any] = {"page": prov.page_no}
    page = doc.pages.get(prov.page_no)
    if page is not None and page.size is not None:
        box = prov.bbox.to_top_left_origin(page_height=page.size.height)
        locator["bbox"] = [round(v, 1) for v in (box.l, box.t, box.r, box.b)]
    return locator


def _cell(value: Any) -> str:
    text = " ".join(str(value).split())
    return "" if text.lower() in {"nan", "none"} else text


def _table_elements(
    item: Any, doc: "DoclingDocument", heading_path: list[str]
) -> Iterator[Element]:
    df = item.export_to_dataframe(doc=doc)
    if df.empty:
        return
    caption = _cell(item.caption_text(doc)) or (heading_path[-1] if heading_path else "Table")
    columns = [_cell(c) for c in df.columns]
    rows = [[_cell(v) for v in row] for row in df.itertuples(index=False)]
    locator = _locator(item, doc)
    markdown = item.export_to_markdown(doc=doc)
    yield Element(
        kind="table",
        content=f"{caption}\n\n{markdown}",
        heading_path=heading_path,
        locator=locator,
        data={"caption": caption, "columns": columns, "rows": rows},
    )
    # One fact per row, so a single value can be retrieved and cited on its own.
    named = not all(c.isdigit() for c in columns)
    for i, row in enumerate(rows[:MAX_ROW_FACTS]):
        cells = [
            f"{col}: {val}" if named and col else val
            for col, val in zip(columns, row, strict=False)
            if val
        ]
        if len(cells) < 2:
            continue
        yield Element(
            kind="table_row",
            content=f"{caption} | " + " | ".join(cells),
            heading_path=heading_path,
            locator={**locator, "row": i + 1},
            data={"caption": caption, "columns": columns, "values": row},
        )


def document_elements(doc: "DoclingDocument") -> Iterator[Element]:
    """Walk a DoclingDocument in reading order and emit elements with their heading path."""
    from docling_core.types.doc import SectionHeaderItem, TableItem, TextItem, TitleItem

    headings: list[tuple[int, str]] = []
    for item, _level in doc.iterate_items():
        label = str(getattr(item, "label", ""))
        if label in SKIP_LABELS:
            continue
        if isinstance(item, TitleItem | SectionHeaderItem):
            text = _cell(item.text)
            if not text:
                continue
            level = 0 if isinstance(item, TitleItem) else heading_level(text, item.level)
            headings = [(lvl, t) for lvl, t in headings if lvl < level] + [(level, text)]
            continue
        path = [t for _, t in headings]
        if isinstance(item, TableItem):
            yield from _table_elements(item, doc, path)
        elif isinstance(item, TextItem):
            text = item.text.strip()
            if text:
                yield Element(
                    kind="text", content=text, heading_path=path, locator=_locator(item, doc)
                )


@lru_cache(maxsize=1)
def _converter(ocr: bool, table_mode: str) -> "DocumentConverter":
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
        TableStructureOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    mode = TableFormerMode.FAST if table_mode == "fast" else TableFormerMode.ACCURATE
    options = PdfPipelineOptions(
        do_ocr=ocr,
        do_table_structure=True,
        table_structure_options=TableStructureOptions(mode=mode),
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


class PdfParser:
    supported_types = frozenset({"application/pdf", ".pdf"})

    def parse(self, file: SourceFile) -> Iterator[Element]:
        settings = get_settings()
        result = _converter(settings.pdf_ocr, settings.pdf_table_mode).convert(file.path)
        yield from document_elements(result.document)

    def release(self) -> None:
        """Drop the Docling models. On a small GPU they and bge-m3 do not fit together."""
        if _converter.cache_info().currsize == 0:
            return
        _converter.cache_clear()
        gc.collect()
        if "torch" in sys.modules:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()


register(PdfParser())
