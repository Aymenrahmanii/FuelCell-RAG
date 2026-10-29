"""System schematics, one per system: components, a line list, a revision block, a title block.

Realism: System A has two revisions (rev B adds a humidifier bypass valve), System B's
drawing is German, and System C's is a raster PNG with no text layer, so it must be read by
OCR. Components come from the truth; supply, exhaust, radiator and purge valve are drawn too,
as on a real schematic, although they carry no parameters.

The topology is defined here without reportlab, so the golden set can import it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fcrag.datagen.common import GeneratedFile
from fcrag.truth import SystemTruth

if TYPE_CHECKING:
    from reportlab.pdfgen.canvas import Canvas


@dataclass(frozen=True)
class Symbol:
    suffix: str
    """Tag after the system code: ``STK`` becomes ``A-STK``."""
    name_en: str
    name_de: str
    x_mm: float
    y_mm: float
    """Centre of the symbol, from the bottom-left page corner."""


@dataclass(frozen=True)
class Line:
    line_id: str
    medium_en: str
    medium_de: str
    source: str
    target: str
    """Tag suffixes, e.g. ``CMP`` to ``HUM``."""


@dataclass(frozen=True)
class Revision:
    rev: str
    description_en: str
    description_de: str
    date: str


@dataclass(frozen=True)
class Drawing:
    code: str
    version: int
    language: str
    raster: bool
    revisions: tuple[Revision, ...]

    @property
    def doc_id(self) -> str:
        return f"dwg-schematic-{self.code.lower()}"

    @property
    def drawing_no(self) -> str:
        return f"DWG-{self.code}-0001"

    @property
    def revision(self) -> str:
        return self.revisions[-1].rev

    @property
    def with_bypass(self) -> bool:
        return any("BPV" in r.description_en for r in self.revisions)


FIRST_ISSUE = Revision("A", "First issue", "Erstausgabe", "2026-03-02")
BYPASS = Revision(
    "B",
    "Humidifier bypass valve {code}-BPV added (lines L14, L15)",
    "Befeuchter-Bypassventil {code}-BPV ergänzt (Leitungen L14, L15)",
    "2026-07-14",
)
DRAWINGS = {
    "A": [
        Drawing("A", 1, "en", False, (FIRST_ISSUE,)),
        Drawing("A", 2, "en", False, (FIRST_ISSUE, BYPASS)),
    ],
    "B": [Drawing("B", 1, "de", False, (Revision("A", "", "Erstausgabe", "2026-04-20"),))],
    "C": [Drawing("C", 1, "en", True, (FIRST_ISSUE,))],
}

NAMES_DE = {
    "stack": "Brennstoffzellenstack",
    "air_compressor": "Elektrischer Turboverdichter",
    "air_blower": "Kathodenluftgebläse",
    "humidifier": "Membranbefeuchter",
    "coolant_pump": "Elektrische Kühlmittelpumpe",
    "h2_recirculation": "Wasserstoff-Rezirkulationsgebläse",
}
AIR_MOVER = {"air_compressor", "air_blower"}
POSITION = {  # symbol centres in mm, by component type
    "stack": (150.0, 165.0),
    "air_mover": (90.0, 250.0),
    "humidifier": (150.0, 250.0),
    "coolant_pump": (90.0, 75.0),
    "h2_recirculation": (90.0, 120.0),
}
EXTERNAL = [
    Symbol("AIR", "Air inlet filter", "Luftfilter", 35.0, 250.0),
    Symbol("EXH", "Exhaust outlet", "Abgasaustritt", 235.0, 250.0),
    Symbol("H2S", "Hydrogen supply", "Wasserstoffversorgung", 35.0, 165.0),
    Symbol("PRG", "Anode purge valve", "Anoden-Spülventil", 235.0, 165.0),
]
RADIATOR = {
    "A": ("Radiator", "Kühler"),
    "B": ("Radiator", "Kühler"),
    "C": ("Heat exchanger (CHP circuit)", "Wärmetauscher (KWK-Kreis)"),
}
BYPASS_VALVE = Symbol("BPV", "Humidifier bypass valve", "Befeuchter-Bypassventil", 150.0, 210.0)

MEDIA = {
    "air": ("Air", "Luft"),
    "humid": ("Humidified air", "Befeuchtete Luft"),
    "exhaust": ("Cathode exhaust", "Kathodenabgas"),
    "h2": ("Hydrogen", "Wasserstoff"),
    "recirc": ("Anode recirculation", "Anodenrezirkulation"),
    "purge": ("Purge gas", "Spülgas"),
    "coolant": ("Coolant", "Kühlmittel"),
}


def symbols(system: SystemTruth, drawing: Drawing) -> list[Symbol]:
    """Every symbol on the drawing: the truth components plus the drawing-only items."""
    out: list[Symbol] = []
    for c in system.components:
        key = "air_mover" if c.type in AIR_MOVER else c.type
        if key not in POSITION:
            continue
        suffix = c.id.split("-", 1)[1]
        name_de = NAMES_DE[c.type] + (" (je Modul)" if "(per module)" in c.name else "")
        out.append(Symbol(suffix, c.name, name_de, *POSITION[key]))
    radiator_en, radiator_de = RADIATOR[system.code]
    out += [*EXTERNAL, Symbol("RAD", radiator_en, radiator_de, 235.0, 75.0)]
    if drawing.with_bypass:
        out.append(BYPASS_VALVE)
    return out


def lines(system: SystemTruth, drawing: Drawing) -> list[Line]:
    """The line list, numbered as it appears on the drawing."""
    mover = next(c.id.split("-", 1)[1] for c in system.components if c.type in AIR_MOVER)
    route = [
        ("air", "AIR", mover), ("air", mover, "HUM"), ("humid", "HUM", "STK"),
        ("exhaust", "STK", "HUM"), ("exhaust", "HUM", "EXH"), ("h2", "H2S", "STK"),
        ("recirc", "STK", "HRB"), ("recirc", "HRB", "STK"), ("purge", "STK", "PRG"),
        ("purge", "PRG", "EXH"), ("coolant", "CLP", "STK"), ("coolant", "STK", "RAD"),
        ("coolant", "RAD", "CLP"),
    ]  # fmt: skip
    if drawing.with_bypass:
        route += [("air", mover, "BPV"), ("air", "BPV", "STK")]
    return [
        Line(f"L{n:02d}", *MEDIA[medium], source, target)
        for n, (medium, source, target) in enumerate(route, 1)
    ]


TEXT: dict[str, dict[str, Any]] = {
    "en": {
        "title": "{system} – fuel cell system schematic",
        "line_list": "Line list",
        "line_header": ("Line", "Medium", "From", "To"),
        "rev_header": ("Rev", "Description", "Date", "By"),
        "block": ("Title", "Drawing no.", "Revision", "Sheet", "Date", "Drawn", "Checked"),
        "note": "Schematic, not to scale. Sensors and check valves are not shown.",
    },
    "de": {
        "title": "{system} – Systemschema Brennstoffzellensystem",
        "line_list": "Leitungsliste",
        "line_header": ("Leitung", "Medium", "Von", "Nach"),
        "rev_header": ("Index", "Änderung", "Datum", "Name"),
        "block": (
            "Benennung", "Zeichnungsnr.", "Index", "Blatt", "Datum", "Gezeichnet", "Geprüft",
        ),
        "note": "Ein Modul dargestellt; das zweite Modul ist baugleich. Ohne Sensoren.",
    },
}  # fmt: skip
BOX_W, BOX_H = 44.0, 18.0
"""Symbol size in mm."""


def _draw_symbols(c: "Canvas", tags: dict[str, Symbol], code: str, language: str) -> None:
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit

    for suffix, s in tags.items():
        x, y = s.x_mm * mm, s.y_mm * mm
        w, h = (60 if suffix == "STK" else BOX_W) * mm, (40 if suffix == "STK" else BOX_H) * mm
        c.setFillColorRGB(1, 1, 1)
        c.rect(x - w / 2, y - h / 2, w, h, fill=1)  # hides the line ends under the symbol
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(x, y + 2 * mm, f"{code}-{suffix}")
        c.setFont("Helvetica", 6.5)
        name = s.name_de if language == "de" else s.name_en
        for i, part in enumerate(simpleSplit(name, "Helvetica", 6.5, w - 4 * mm)):
            c.drawCentredString(x, y - 1.5 * mm - i * 3 * mm, part)


def _draw_lines(c: "Canvas", tags: dict[str, Symbol], drawn: list[Line]) -> None:
    """Orthogonal connections: horizontal from the source, then vertical into the target.

    Each line ID is written where its run is longest, at a staggered position so parallel
    lines do not stack their labels."""
    from reportlab.lib.units import mm

    for n, line in enumerate(drawn):
        a, b = tags[line.source], tags[line.target]
        offset = (n % 5 - 2) * 2.0  # keep parallel lines apart
        x1, y1 = a.x_mm, a.y_mm + offset
        x2, y2 = b.x_mm + offset, b.y_mm
        c.setLineWidth(0.6)
        c.line(x1 * mm, y1 * mm, x2 * mm, y1 * mm)
        c.line(x2 * mm, y1 * mm, x2 * mm, y2 * mm)
        at = 0.3 + 0.1 * (n % 5)
        if abs(x2 - x1) >= abs(y2 - y1):
            label = (x1 + (x2 - x1) * at + 1, y1 + 1)
        else:
            label = (x2 + 1, y1 + (y2 - y1) * at)
        c.setFont("Helvetica", 5.5)
        c.drawString(label[0] * mm, label[1] * mm, line.line_id)


def _draw_table(
    c: "Canvas", x_mm: float, top_mm: float, widths: list[float], rows: list[tuple[str, ...]]
) -> float:
    """A ruled table, header row first; returns the bottom edge in mm."""
    from reportlab.lib.units import mm

    row_h = 5.0
    for r, row in enumerate(rows):
        y = top_mm - (r + 1) * row_h
        c.setFont("Helvetica-Bold" if r == 0 else "Helvetica", 6)
        x = x_mm
        for width, cell in zip(widths, row, strict=True):
            c.rect(x * mm, y * mm, width * mm, row_h * mm)
            c.drawString((x + 1.2) * mm, (y + 1.6) * mm, cell)
            x += width
    return top_mm - len(rows) * row_h


def _draw_title_block(c: "Canvas", fields: list[tuple[str, str]]) -> None:
    """Label above value in each cell: title across the top, then two rows of three cells."""
    from reportlab.lib.units import mm

    x0, top, width, row_h = 275.0, 58.0, 135.0, 14.0
    cells = [(x0, top, width, fields[0])] + [
        (x0 + (i % 3) * width / 3, top - row_h * (1 + i // 3), width / 3, field)
        for i, field in enumerate(fields[1:])
    ]
    for x, y_top, w, (label, value) in cells:
        c.rect(x * mm, (y_top - row_h) * mm, w * mm, row_h * mm)
        c.setFont("Helvetica", 5.5)
        c.drawString((x + 1.5) * mm, (y_top - 4) * mm, label)
        c.setFont("Helvetica-Bold", 8)
        c.drawString((x + 1.5) * mm, (y_top - 9.5) * mm, value)


def render_pdf(system: SystemTruth, drawing: Drawing, path: Path) -> None:
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas

    t = TEXT[drawing.language]
    de = drawing.language == "de"
    tags = {s.suffix: s for s in symbols(system, drawing)}
    drawn = lines(system, drawing)
    c = Canvas(str(path), pagesize=landscape(A3))
    c.setTitle(t["title"].format(system=system.system))
    c.rect(10 * mm, 10 * mm, 400 * mm, 277 * mm)
    _draw_lines(c, tags, drawn)
    _draw_symbols(c, tags, system.code, drawing.language)
    c.setFont("Helvetica-Oblique", 6.5)
    c.drawString(15 * mm, 15 * mm, t["note"])

    c.setFont("Helvetica-Bold", 7)
    c.drawString(275 * mm, 278 * mm, t["line_list"])
    line_rows = [t["line_header"]] + [
        (
            ln.line_id,
            ln.medium_de if de else ln.medium_en,
            f"{system.code}-{ln.source}",
            f"{system.code}-{ln.target}",
        )
        for ln in drawn
    ]
    _draw_table(c, 275.0, 276.0, [15.0, 50.0, 35.0, 35.0], line_rows)

    rev_rows = [t["rev_header"]] + [
        (r.rev, (r.description_de if de else r.description_en).format(code=system.code),
         r.date, "FC-Design")
        for r in drawing.revisions
    ]  # fmt: skip
    _draw_table(c, 275.0, 62.0 + 5.0 * len(rev_rows), [12.0, 85.0, 20.0, 18.0], rev_rows)

    last = drawing.revisions[-1]
    values = [
        t["title"].format(system=system.system), drawing.drawing_no, drawing.revision, "1/1",
        last.date, "FC-Design", "FC-Systems",
    ]  # fmt: skip
    _draw_title_block(c, list(zip(t["block"], values, strict=True)))
    c.showPage()
    c.save()


RASTER_DPI = 250


def render_png(pdf_path: Path, png_path: Path) -> None:
    """Rasterise the first page in greyscale: a scan with no text layer."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        image = pdf[0].render(scale=RASTER_DPI / 72, grayscale=True).to_pil()
        image.save(png_path, dpi=(RASTER_DPI, RASTER_DPI))
    finally:
        pdf.close()


def build_drawing(system: SystemTruth, drawing: Drawing, out_dir: Path) -> GeneratedFile:
    versioned = len(DRAWINGS[system.code]) > 1
    stem = f"{drawing.doc_id}_v{drawing.version}" if versioned else drawing.doc_id
    title = TEXT[drawing.language]["title"].format(system=system.system)
    out = GeneratedFile(
        file=f"{stem}.png" if drawing.raster else f"{stem}.pdf",
        doc_id=drawing.doc_id,
        doc_version=drawing.version,
        title=f"{title} (rev {drawing.revision})",
        system=system.system,
        doc_type="drawing",
        language=drawing.language,
    )
    pdf_path = out_dir / f"{stem}.pdf"
    render_pdf(system, drawing, pdf_path)
    if drawing.raster:
        render_png(pdf_path, out_dir / out.file)
        pdf_path.unlink()
    return out


def build_all(system: SystemTruth, out_dir: Path) -> list[GeneratedFile]:
    return [build_drawing(system, d, out_dir) for d in DRAWINGS.get(system.code, [])]
