"""Drawing parser: schematics and P&IDs as PDF (vector or scanned) or image.

Text comes from the PDF text layer when there is one, otherwise from OCR (RapidOCR, in the
``ml`` extra). Either way the page becomes positioned text segments, and the layout is read
from their geometry: the line list and revision table by their header rows, the title block
by its field labels, components by their tags with the name lines below.

Each sheet yields one ``drawing`` element with components and connections, and one with the
title block and revision history. With ``drawing_vlm`` enabled, a vision model adds a third
element describing the sheet; it is marked as low confidence because it can invent details.
"""

import base64
import io
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fcrag.config import Settings, get_settings
from fcrag.ingest.parsers import register
from fcrag.models import Element, SourceFile

if TYPE_CHECKING:
    from PIL.Image import Image

log = logging.getLogger(__name__)

IMAGE_TYPES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff"})
OCR_SCALE = 3.0
"""Render scale for scanned PDF pages: 216 dpi keeps 6 pt labels readable."""
OCR_MAX_PX = 4200
"""Longest image side given to OCR. RapidOCR shrinks to 2,000 px by default, which turns
6 pt labels on an A3 sheet into guesses ("Tle" for "Title")."""
VLM_MAX_PX = 2048

TAG = re.compile(r"^[A-Z]{1,3}-[A-Z0-9]{2,5}(?:-\d{1,3})?$")
"""Component tags such as ``A-STK`` or ``B-V-01``; drawing numbers (``DWG-A-0001``) do not
match because the second group needs two characters."""
LINE_LABEL = re.compile(r"^L\s?\d{1,3}$")
REV_ID = re.compile(r"^(?:[A-Z]|\d{1,2})$")

LINE_COLUMNS = {
    "line": {"line", "leitung", "line no.", "linie"},
    "medium": {"medium", "fluid"},
    "from": {"from", "von"},
    "to": {"to", "nach", "bis"},
}
REV_COLUMNS = {
    "rev": {"rev", "rev.", "revision", "index"},
    "description": {"description", "änderung", "aenderung", "beschreibung"},
    "date": {"date", "datum"},
    "by": {"by", "name"},
}
TITLE_FIELDS = {
    "title": {"title", "benennung"},
    "drawing_no": {"drawing no.", "drawing no", "dwg no.", "zeichnungsnr.", "zeichnungsnummer"},
    "revision": {"revision", "rev.", "index"},
    "sheet": {"sheet", "blatt"},
    "date": {"date", "datum"},
    "drawn": {"drawn", "gezeichnet"},
    "checked": {"checked", "geprüft"},
    "scale": {"scale", "maßstab"},
}
CAPTIONS = {"line list", "leitungsliste", "revisions", "änderungen"}

TEXT: dict[str, dict[str, Any]] = {
    "en": {
        "drawing": "Drawing", "rev": "rev", "sheet": "sheet", "components": "Components",
        "lines": "Line list", "from": "from", "to": "to", "notes": "Notes",
        "other": "Text on the drawing", "block": "Title block of drawing",
        "history": "Revision history", "vlm": "Vision model description of drawing",
        "unverified": "unverified, check against the drawing",
        "fields": {
            "title": "Title", "drawing_no": "Drawing no.", "revision": "Revision",
            "sheet": "Sheet", "date": "Date", "drawn": "Drawn", "checked": "Checked",
            "scale": "Scale",
        },
    },
    "de": {
        "drawing": "Zeichnung", "rev": "Index", "sheet": "Blatt", "components": "Komponenten",
        "lines": "Leitungsliste", "from": "von", "to": "nach", "notes": "Hinweise",
        "other": "Text auf der Zeichnung", "block": "Schriftfeld der Zeichnung",
        "history": "Änderungshistorie", "vlm": "Beschreibung durch ein Vision-Modell, Zeichnung",
        "unverified": "nicht geprüft, mit der Zeichnung abgleichen",
        "fields": {
            "title": "Benennung", "drawing_no": "Zeichnungsnr.", "revision": "Index",
            "sheet": "Blatt", "date": "Datum", "drawn": "Gezeichnet", "checked": "Geprüft",
            "scale": "Maßstab",
        },
    },
}  # fmt: skip


@dataclass(eq=False)
class Segment:
    """A run of text on one line, in page units with the origin at the top left."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def h(self) -> float:
        return max(self.y1 - self.y0, 1e-6)

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def key(self) -> str:
        return " ".join(self.text.split()).lower().rstrip(":")


@dataclass
class Sheet:
    """What the layout analysis found on one page."""

    title_block: dict[str, str] = field(default_factory=dict)
    components: list[dict[str, str]] = field(default_factory=list)
    lines: list[dict[str, str]] = field(default_factory=list)
    revisions: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --- text extraction ---------------------------------------------------------------------


def group_rows(segments: list[Segment]) -> list[list[Segment]]:
    """Segments on the same text line, top to bottom, each row sorted left to right, with
    runs that touch merged (a PDF text layer splits lines at spaces and font changes)."""
    rows: list[list[Segment]] = []
    for seg in sorted(segments, key=lambda s: s.yc):
        if rows and abs(seg.yc - rows[-1][0].yc) < 0.5 * min(seg.h, rows[-1][0].h):
            rows[-1].append(seg)
        else:
            rows.append([seg])
    return [_merge_runs(sorted(row, key=lambda s: s.x0)) for row in rows]


def _merge_runs(row: list[Segment]) -> list[Segment]:
    merged: list[Segment] = []
    for seg in row:
        prev = merged[-1] if merged else None
        if prev is not None and seg.x0 - prev.x1 < 0.6 * min(prev.h, seg.h):
            gap = seg.x0 - prev.x1
            joiner = " " if gap > 0.12 * prev.h or prev.text.endswith(" ") else ""
            merged[-1] = Segment(
                f"{prev.text.rstrip()}{joiner}{seg.text.lstrip()}",
                prev.x0, min(prev.y0, seg.y0), seg.x1, max(prev.y1, seg.y1),
            )  # fmt: skip
        else:
            merged.append(Segment(seg.text, seg.x0, seg.y0, seg.x1, seg.y1))
    return [s for s in merged if s.text.strip()]


def pdf_segments(page: Any) -> list[Segment]:
    """Text runs of a pypdfium2 page, from its text layer, character by character in content
    order: reading text by region would also pick up labels hidden under a symbol."""
    height = page.get_size()[1]
    textpage = page.get_textpage()
    try:
        segments: list[Segment] = []
        run: Segment | None = None
        for i in range(textpage.count_chars()):
            char = textpage.get_text_range(i, 1)
            if char in ("\r", "\n", ""):
                run = None
                continue
            left, bottom, right, top = textpage.get_charbox(i)
            if char.isspace() or right <= left:
                if run is not None:
                    run.text += char
                continue
            y0, y1 = height - top, height - bottom
            same_line = run is not None and y0 < run.y1 and y1 > run.y0  # commas sit low
            if run is None or not same_line or not -run.h < left - run.x1 < run.h:
                run = Segment(char, left, y0, right, y1)
                segments.append(run)
            else:
                run.text += char
                run.x1, run.y0, run.y1 = right, min(run.y0, y0), max(run.y1, y1)
        return [s for s in segments if s.text.strip()]
    finally:
        textpage.close()


@lru_cache(maxsize=1)
def _ocr_engine() -> Any:
    try:
        from rapidocr import RapidOCR

        return RapidOCR(
            params={
                "Global.max_side_len": OCR_MAX_PX,
                "Det.limit_side_len": OCR_MAX_PX,
                "Det.limit_type": "max",
            }
        )
    except ImportError as exc:  # rapidocr itself, or its onnxruntime engine
        raise RuntimeError(
            "OCR of drawings needs RapidOCR (uv sync --extra ml) and onnxruntime"
        ) from exc


def ocr_segments(image: "Image") -> list[Segment]:
    """Text boxes found by OCR, in pixels."""
    if max(image.size) > OCR_MAX_PX:
        image = image.copy()
        image.thumbnail((OCR_MAX_PX, OCR_MAX_PX))
    result = _ocr_engine()(image)
    if result.txts is None:
        return []
    segments = []
    for box, text in zip(result.boxes, result.txts, strict=True):
        xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
        segments.append(Segment(str(text), min(xs), min(ys), max(xs), max(ys)))
    return segments


# --- layout analysis ---------------------------------------------------------------------


def _find_header(row: list[Segment], columns: dict[str, set[str]]) -> dict[str, Segment] | None:
    found: dict[str, Segment] = {}
    for name, aliases in columns.items():
        match = next((s for s in row if s.key in aliases and s not in found.values()), None)
        if match is None:
            return None
        found[name] = match
    return found


def read_table(
    rows: list[list[Segment]],
    columns: dict[str, set[str]],
    first: re.Pattern[str],
    used: set[int],
) -> list[dict[str, str]]:
    """Rows under a header row naming every column; stops at the first row whose leading cell
    does not match ``first`` or that sits too far below the previous one."""
    for r, row in enumerate(rows):
        header = _find_header([s for s in row if id(s) not in used], columns)
        if header is None:
            continue
        cols = sorted(header.items(), key=lambda item: item[1].x0)
        left, h = cols[0][1].x0, cols[0][1].h
        table: list[dict[str, str]] = []
        last_y, step = cols[0][1].yc, 0.0
        for below in rows[r + 1 :]:
            cells = [s for s in below if s.x0 >= left - h and id(s) not in used]
            if not cells:  # diagram text left of the table, between two of its rows
                continue
            if not first.match(cells[0].text.strip()):
                break
            gap = cells[0].yc - last_y
            if gap > (1.8 * step if step else 6 * h):
                break
            step = step or gap
            record: dict[str, str] = {}
            for seg in cells:
                name = next((n for n, s in reversed(cols) if s.x0 <= seg.x0 + h), cols[0][0])
                record[name] = f"{record.get(name, '')} {seg.text.strip()}".strip()
                used.add(id(seg))
            table.append(record)
            last_y = cells[0].yc
        if table:
            used.update(id(s) for s in header.values())
            return table
    return []


def read_title_block(segments: list[Segment], used: set[int]) -> dict[str, str]:
    """Each field label with the value written just below it, left-aligned."""
    labels = {alias: name for name, aliases in TITLE_FIELDS.items() for alias in aliases}
    free = [s for s in segments if id(s) not in used]
    block: dict[str, str] = {}
    for label in free:
        name = labels.get(label.key)
        if name is None or name in block:
            continue
        below = [
            s for s in free
            if s is not label and id(s) not in used and s.key not in labels
            and 0 <= s.y0 - label.y1 < 4 * label.h and abs(s.x0 - label.x0) < 2 * label.h
        ]  # fmt: skip
        if below:
            value = min(below, key=lambda s: s.y0)
            block[name] = value.text.strip()
            used.update((id(label), id(value)))
    return block


def read_components(segments: list[Segment], used: set[int]) -> list[dict[str, str]]:
    """Tags with their names: the text lines centred under each tag."""
    free = sorted((s for s in segments if id(s) not in used), key=lambda s: (s.y0, s.x0))
    found: list[dict[str, str]] = []
    for tag in free:
        if id(tag) in used or not TAG.match(tag.text.strip()):
            continue
        used.add(id(tag))
        name, bottom = [], tag.y1
        for seg in free:
            text = seg.text.strip()
            if id(seg) in used or TAG.match(text) or LINE_LABEL.match(text):
                continue
            if seg.y0 < bottom - 0.3 * seg.h:
                continue
            if seg.y0 - bottom > 1.5 * tag.h:
                continue
            if abs(seg.xc - tag.xc) < max(seg.x1 - seg.x0, tag.x1 - tag.x0) / 2:
                name.append(seg.text.strip())
                used.add(id(seg))
                bottom = seg.y1
        found.append({"tag": tag.text.strip(), "name": " ".join(name)})
    return found


def analyse(segments: list[Segment]) -> Sheet:
    rows = group_rows(segments)
    merged = [s for row in rows for s in row]
    used: set[int] = set()
    sheet = Sheet()
    # Tables first: their headers ("Date", "Index") reuse title block labels
    sheet.lines = read_table(rows, LINE_COLUMNS, LINE_LABEL, used)
    sheet.revisions = read_table(rows, REV_COLUMNS, REV_ID, used)
    sheet.title_block = read_title_block(merged, used)
    sheet.components = read_components(merged, used)
    for row in rows:
        text = " ".join(
            s.text.strip() for s in row
            if id(s) not in used and not LINE_LABEL.match(s.text.strip())
            and s.key not in CAPTIONS
        )  # fmt: skip
        if text:
            sheet.notes.append(text)
    return sheet


# --- elements ----------------------------------------------------------------------------


def _describe(sheet: Sheet, language: str) -> tuple[str, str]:
    """Heading (the drawing number: the document title already names the drawing) and
    content of the components-and-connections element."""
    t = TEXT[language]
    block = sheet.title_block
    title = block.get("title", "")
    number = block.get("drawing_no", "")
    head = " ".join(
        p for p in (
            t["drawing"], number, f"{t['rev']} {block['revision']}" if "revision" in block else "",
        ) if p
    )  # fmt: skip
    if "sheet" in block:
        head += f", {t['sheet']} {block['sheet']}"
    parts = []
    if number or title:
        parts.append(f"{head}: {title}." if title else f"{head}.")
    names = {c["tag"]: c["name"] for c in sheet.components}
    if sheet.components:
        parts.append(f"{t['components']}:")
        parts += [f"- {c['tag']}: {c['name']}" if c["name"] else f"- {c['tag']}"
                  for c in sheet.components]  # fmt: skip

    def end(tag: str) -> str:
        return f"{tag} ({names[tag]})" if names.get(tag) else tag

    if sheet.lines:
        parts.append(f"{t['lines']}:")
        for line in sheet.lines:
            medium = f" {line['medium']}" if line.get("medium") else ""
            parts.append(
                f"- {line['line']}{medium} {t['from']} {end(line.get('from', '?'))} "
                f"{t['to']} {end(line.get('to', '?'))}"
            )
    if sheet.notes:
        label = t["notes"] if sheet.components or sheet.lines else t["other"]
        parts.append(f"{label}: " + " ".join(sheet.notes))
    return number or title, "\n".join(parts)


def _title_block_text(sheet: Sheet, language: str) -> str:
    t = TEXT[language]
    fields = "; ".join(f"{t['fields'][k]}: {v}" for k, v in sheet.title_block.items())
    parts = [f"{t['block']} {sheet.title_block.get('drawing_no', '')}: {fields}."]
    if sheet.revisions:
        parts.append(f"{t['history']}:")
        for rev in sheet.revisions:
            meta = ", ".join(v for v in (rev.get("date"), rev.get("by")) if v)
            parts.append(
                f"- {t['rev']} {rev.get('rev', '?')}"
                + (f" ({meta})" if meta else "") + f": {rev.get('description', '')}"
            )  # fmt: skip
    return "\n".join(parts)


def _vlm_model(settings: Settings) -> str | None:
    if not settings.drawing_vlm:
        return None
    # Restricted mode: a hosted vision model would see the drawing, so only a local one
    return settings.local_vlm_model if settings.restricted_mode else settings.vlm_model


def describe_with_vlm(image: "Image", model: str, context: str, language: str) -> str | None:
    """Ask a vision model what the sheet shows; None if the call fails (ingestion goes on)."""
    import litellm

    from fcrag.generation.answer import load_prompt

    prompt = load_prompt("drawing")
    image = image.convert("RGB")
    image.thumbnail((VLM_MAX_PX, VLM_MAX_PX))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    language_name = "German" if language == "de" else "English"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt["system"].format(language_name=language_name)},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt["user"].format(context=context)},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    try:
        response: Any = litellm.completion(
            model=model, messages=messages, temperature=0,
            timeout=get_settings().llm_timeout_s, num_retries=1,
        )  # fmt: skip
        text = response.choices[0].message.content
        return str(text).strip() or None
    except Exception as exc:
        log.warning("vision model %s failed on a drawing, skipping its description: %s", model, exc)
        return None


@dataclass
class Page:
    number: int
    segments: list[Segment]
    source: str
    """``pdf`` (text layer) or ``ocr``."""
    image: "Image | None" = None
    """The rendered page, kept only when OCR or the vision model needs it."""


class DrawingParser:
    supported_types = IMAGE_TYPES | frozenset({"image/png", "image/jpeg", "image/tiff"})
    doc_types = frozenset({"drawing"})
    """PDFs registered as drawings come here instead of the report parser."""

    def pages(self, path: Path, keep_image: bool) -> Iterator[Page]:
        if path.suffix.lower() in IMAGE_TYPES:
            from PIL import Image

            with Image.open(path) as image:
                image.load()
                yield Page(1, ocr_segments(image), "ocr", image if keep_image else None)
            return
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                segments = pdf_segments(page)
                if segments and not keep_image:
                    yield Page(i + 1, segments, "pdf")
                    continue
                image = page.render(scale=OCR_SCALE).to_pil()
                if segments:
                    yield Page(i + 1, segments, "pdf", image)
                else:
                    yield Page(i + 1, ocr_segments(image), "ocr", image)
        finally:
            pdf.close()

    def parse(self, file: SourceFile) -> Iterator[Element]:
        language = file.language if file.language in TEXT else "en"
        model = _vlm_model(get_settings())
        for page in self.pages(file.path, keep_image=model is not None):
            sheet = analyse(page.segments)
            heading, content = _describe(sheet, language)
            heading = heading or file.title or file.path.stem
            locator: dict[str, Any] = {"page": page.number}
            for key in ("drawing_no", "revision"):
                if key in sheet.title_block:
                    locator[key] = sheet.title_block[key]
            data: dict[str, Any] = {
                "title_block": sheet.title_block, "components": sheet.components,
                "lines": sheet.lines, "revisions": sheet.revisions, "text_source": page.source,
            }  # fmt: skip
            yield Element(
                kind="drawing", content=content, heading_path=[heading], locator=locator,
                data=data,
            )  # fmt: skip
            if sheet.title_block or sheet.revisions:
                yield Element(
                    kind="drawing", content=_title_block_text(sheet, language),
                    heading_path=[heading], locator=locator,
                    data={"title_block": sheet.title_block, "revisions": sheet.revisions},
                )  # fmt: skip
            if model is not None and page.image is not None:
                description = describe_with_vlm(page.image, model, content, language)
                if description:
                    t = TEXT[language]
                    number = sheet.title_block.get("drawing_no", heading)
                    yield Element(
                        kind="drawing",
                        content=f"{t['vlm']} {number} ({t['unverified']}):\n{description}",
                        heading_path=[heading],
                        locator={**locator, "source": "vision_model"},
                        data={"confidence": "low", "model": model},
                    )

    def release(self) -> None:
        _ocr_engine.cache_clear()


register(DrawingParser())
