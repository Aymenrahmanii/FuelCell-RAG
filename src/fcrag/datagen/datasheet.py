"""Datasheet PDFs (reportlab): one per system and document version, and one per component.

Realism: tables plus prose limits, repeated page headers and footers, a German datasheet with
decimal commas, unit variants (bar instead of kPa, K instead of °C) and a revision history.
Component datasheets come from the supplier side: a part number, their own unit conventions,
and versions only where one of the component's own values changed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from fcrag.datagen.common import (
    GeneratedFile,
    convert,
    doc_versions,
    format_number,
    label,
    make_fact,
    value_at_version,
)
from fcrag.truth import Component, SystemTruth, TruthParameter
from fcrag.units import display_unit


@dataclass(frozen=True)
class Style:
    """Per-system document conventions (the realism injections)."""

    language: str
    unit_variants: dict[str, str]
    """Truth unit to the unit this document uses instead, e.g. ``{"kPa": "bar"}``."""


STYLES = {
    "A": Style("en", {}),
    "B": Style("de", {"kPa": "bar"}),
    "C": Style("en", {"degC": "K"}),
}
COMPONENT_STYLES = {
    "A": Style("en", {"kPa": "bar"}),
    "B": Style("de", {}),
    "C": Style("en", {"degC": "K", "kPa": "bar"}),
}
"""Suppliers keep their own units, so a value can read differently in the system datasheet."""

TEXT: dict[str, dict[str, Any]] = {
    "en": {
        "title": "Fuel Cell System Datasheet",
        "overview": "Overview",
        "performance": "System performance",
        "stack": "Fuel cell stack",
        "electrical": "Electrical characteristics",
        "limits": "Operating limits",
        "materials": "Materials and catalyst",
        "design": "Design",
        "bop": "Balance of plant",
        "history": "Revision history",
        "header": ["Parameter", "Value", "Unit", "Condition"],
        "application": "Application",
        "page": "Page",
        "synthetic": "Synthetic document generated for FuelCell-RAG. Not a real product.",
        "rev": "Revision",
        "lhv": "Efficiencies refer to the lower heating value (LHV) of hydrogen.",
        "limit_sentence": "The {label} is {value}{unit}{condition}.",
        "initial": "Initial release.",
        "changed": "{label} changed from {old} {unit} to {new} {unit}.",
        "component_title": "Component Datasheet",
        "part_no": "Part no.",
        "used_in": "Used in",
        "ratings": "Ratings",
    },
    "de": {
        "title": "Datenblatt Brennstoffzellensystem",
        "overview": "Übersicht",
        "performance": "Systemleistung",
        "stack": "Brennstoffzellenstack",
        "electrical": "Elektrische Kennwerte",
        "limits": "Betriebsgrenzen",
        "materials": "Werkstoffe und Katalysator",
        "design": "Konstruktion",
        "bop": "Systemperipherie (Balance of Plant)",
        "history": "Änderungshistorie",
        "header": ["Parameter", "Wert", "Einheit", "Bedingung"],
        "application": "Anwendung",
        "page": "Seite",
        "synthetic": "Synthetisches Dokument, erzeugt für FuelCell-RAG. Kein reales Produkt.",
        "rev": "Revision",
        "lhv": "Wirkungsgrade beziehen sich auf den unteren Heizwert (Hu) von Wasserstoff.",
        "limit_sentence": "{label}: {value}{unit}{condition}.",
        "initial": "Erstausgabe.",
        "changed": "{label} geändert von {old} {unit} auf {new} {unit}.",
        "component_title": "Komponentendatenblatt",
        "part_no": "Teilenummer",
        "used_in": "Eingesetzt in",
        "ratings": "Kennwerte",
    },
}

ELECTRICAL = {
    "cell_count", "active_area", "rated_gross_power", "rated_current", "rated_current_density",
    "cell_voltage_rated", "stack_voltage_rated", "open_circuit_voltage",
}  # fmt: skip
MATERIALS = {
    "pt_loading_cathode", "pt_loading_anode", "membrane_thickness", "stack_mass", "stack_volume",
}  # fmt: skip


class FactTable(Table):
    facts: list[tuple[Component | None, TruthParameter, float, str]]


class FactParagraph(Paragraph):
    facts: list[tuple[Component | None, TruthParameter, float, str]]


class _TrackingDoc(SimpleDocTemplate):
    """Records the page each fact-carrying flowable lands on."""

    def __init__(self, path: str, out: GeneratedFile, system: SystemTruth, **kw: Any) -> None:
        super().__init__(path, **kw)
        self.out, self.system = out, system

    def afterFlowable(self, flowable: Flowable) -> None:  # noqa: N802 (reportlab hook)
        for component, param, value, unit in getattr(flowable, "facts", []):
            self.out.facts.append(
                make_fact(self.system, component, param, value, unit, self.out, {"page": self.page})
            )


def _stated(param: TruthParameter, version: int, style: Style) -> tuple[float, str]:
    value = value_at_version(param, version)
    target = style.unit_variants.get(param.unit)
    return (convert(value, param.unit, target), target) if target else (value, param.unit)


def _table(
    rows: Sequence[tuple[Component | None, TruthParameter]], version: int, style: Style
) -> FactTable:
    t = TEXT[style.language]
    data: list[list[Any]] = [t["header"]]
    facts = []
    cell = ParagraphStyle("cell", fontSize=8, leading=10)
    for component, param in rows:
        value, unit = _stated(param, version, style)
        data.append(
            [
                Paragraph(label(param, style.language), cell),
                format_number(value, style.language),
                display_unit(unit),
                Paragraph(param.condition or "", cell),
            ]
        )
        facts.append((component, param, value, unit))
    table = FactTable(data, colWidths=[62 * mm, 25 * mm, 20 * mm, 63 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe7ef")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8a99a8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ]
        )
    )
    table.facts = facts
    return table


def _limit_paragraphs(
    component: Component, params: list[TruthParameter], version: int, style: Style, body: Any
) -> list[FactParagraph]:
    t = TEXT[style.language]
    out = []
    for param in params:
        value, unit = _stated(param, version, style)
        name = label(param, style.language)
        condition = f" ({param.condition})" if param.condition else ""
        text = t["limit_sentence"].format(
            label=name if style.language == "de" else name[0].lower() + name[1:],
            value=format_number(value, style.language),
            unit="" if unit == "-" else f" {display_unit(unit)}",
            condition=condition,
        )
        p = FactParagraph(text, body)
        p.facts = [(component, param, value, unit)]
        out.append(p)
    return out


def _revision_history(params: list[TruthParameter], version: int, style: Style) -> list[str]:
    t = TEXT[style.language]
    lines = [f"{t['rev']} 1: {t['initial']}"]
    for v in range(2, version + 1):
        for p in params:
            for r in p.superseded:
                if r.doc_version == v - 1:
                    old, new = value_at_version(p, v - 1), value_at_version(p, v)
                    change = t["changed"].format(
                        label=label(p, style.language),
                        old=format_number(old, style.language),
                        new=format_number(new, style.language),
                        unit=display_unit(p.unit),
                    )
                    lines.append(f"{t['rev']} {v}: {change} {r.note or ''}".strip())
    return lines


def build_datasheet(system: SystemTruth, version: int, out_dir: Path) -> GeneratedFile:
    style = STYLES[system.code]
    t = TEXT[style.language]
    doc_id = f"ds-system-{system.code.lower()}"
    out = GeneratedFile(
        file=f"{doc_id}_v{version}.pdf",
        doc_id=doc_id,
        doc_version=version,
        title=f"{system.system} {t['title']}",
        system=system.system,
        doc_type="datasheet",
        language=style.language,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12)
    h1, h2 = styles["Heading1"], styles["Heading2"]

    def on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(20 * mm, 287 * mm, f"{system.system} · {t['title']} · {doc_id.upper()}")
        canvas.drawRightString(190 * mm, 287 * mm, f"{t['rev']} {version}")
        canvas.drawString(20 * mm, 10 * mm, t["synthetic"])
        canvas.drawRightString(190 * mm, 10 * mm, f"{t['page']} {doc.page}")
        canvas.restoreState()

    story: list[Flowable] = [
        Paragraph(f"{system.system} – {t['title']}", styles["Title"]),
        Paragraph(f"{doc_id.upper()} · {t['rev']} {version}", body),
        Spacer(1, 4 * mm),
        Paragraph(f"1 {t['overview']}", h1),
        Paragraph(system.description, body),
        Paragraph(f"<b>{t['application']}:</b> {system.application}", body),
        Paragraph(f"2 {t['performance']}", h1),
        KeepTogether([_table([(None, p) for p in system.parameters], version, style)]),
        Paragraph(t["lhv"], body),
    ]

    stack = next(c for c in system.components if c.type == "stack")
    electrical = [p for p in stack.parameters if p.key in ELECTRICAL]
    materials = [p for p in stack.parameters if p.key in MATERIALS]
    limits = [p for p in stack.parameters if p.key not in ELECTRICAL | MATERIALS]
    design = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in stack.attributes.items())
    story += [
        Paragraph(f"3 {t['stack']}", h1),
        Paragraph(f"<b>{t['design']}:</b> {design}", body),
        Paragraph(f"3.1 {t['electrical']}", h2),
        KeepTogether([_table([(stack, p) for p in electrical], version, style)]),
        Paragraph(f"3.2 {t['limits']}", h2),
        *_limit_paragraphs(stack, limits, version, style, body),
        Paragraph(f"3.3 {t['materials']}", h2),
        KeepTogether([_table([(stack, p) for p in materials], version, style)]),
        Paragraph(f"4 {t['bop']}", h1),
    ]
    for n, component in enumerate((c for c in system.components if c.type != "stack"), 1):
        attrs = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in component.attributes.items())
        block: list[Flowable] = [Paragraph(f"4.{n} {component.name} ({component.id})", h2)]
        if attrs:
            block.append(Paragraph(attrs, body))
        block.append(_table([(component, p) for p in component.parameters], version, style))
        story.append(KeepTogether(block))
    story.append(Paragraph(f"5 {t['history']}", h1))
    params = list(system.parameters) + [p for c in system.components for p in c.parameters]
    story += [Paragraph(line, body) for line in _revision_history(params, version, style)]

    doc = _TrackingDoc(
        str(out_dir / out.file),
        out,
        system,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=out.title,
        author="FuelCell-RAG data generator",
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out


def part_number(component: Component) -> str:
    """Supplier part number, stable across regenerations."""
    code, suffix = component.id.split("-", 1)
    return f"FCR-{suffix}-{ord(code) * 7 % 100:02d}{len(component.parameters):02d}"


def component_versions(component: Component) -> int:
    return max((p.current_doc_version for p in component.parameters), default=1)


def build_component_datasheet(
    system: SystemTruth, component: Component, version: int, out_dir: Path
) -> GeneratedFile:
    from fcrag.datagen.drawing import NAMES_DE

    style = COMPONENT_STYLES[system.code]
    t = TEXT[style.language]
    doc_id = f"cds-{component.id.lower()}"
    name = component.name
    if style.language == "de":
        name = NAMES_DE[component.type] + (" (je Modul)" if "(per module)" in name else "")
    out = GeneratedFile(
        file=f"{doc_id}_v{version}.pdf",
        doc_id=doc_id,
        doc_version=version,
        title=f"{name} ({component.id}) {t['component_title']}",
        system=system.system,
        doc_type="datasheet",
        language=style.language,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12)
    h1 = styles["Heading1"]

    def on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(20 * mm, 287 * mm, f"{t['component_title']} · {part_number(component)}")
        canvas.drawRightString(190 * mm, 287 * mm, f"{t['rev']} {version}")
        canvas.drawString(20 * mm, 10 * mm, t["synthetic"])
        canvas.drawRightString(190 * mm, 10 * mm, f"{t['page']} {doc.page}")
        canvas.restoreState()

    story: list[Flowable] = [
        Paragraph(f"{name} – {t['component_title']}", styles["Title"]),
        Paragraph(
            f"{t['part_no']} {part_number(component)} · {component.id} · {t['rev']} {version}", body
        ),
        Paragraph(f"<b>{t['used_in']}:</b> {system.system} ({system.application})", body),
        Spacer(1, 4 * mm),
    ]
    n = 1
    if component.attributes:
        story.append(Paragraph(f"{n} {t['design']}", h1))
        story += [
            Paragraph(f"<b>{k.replace('_', ' ').capitalize()}:</b> {v}", body)
            for k, v in component.attributes.items()
        ]
        n += 1
    story += [
        Paragraph(f"{n} {t['ratings']}", h1),
        _table([(component, p) for p in component.parameters], version, style),
        Paragraph(f"{n + 1} {t['history']}", h1),
        *[
            Paragraph(line, body)
            for line in _revision_history(component.parameters, version, style)
        ],
    ]
    doc = _TrackingDoc(
        str(out_dir / out.file), out, system, pagesize=A4, leftMargin=20 * mm,
        rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=18 * mm, title=out.title,
        author="FuelCell-RAG data generator",
    )  # fmt: skip
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out


def build_all(system: SystemTruth, out_dir: Path) -> list[GeneratedFile]:
    files = [build_datasheet(system, v, out_dir) for v in range(1, doc_versions(system) + 1)]
    for component in system.components:
        files += [
            build_component_datasheet(system, component, v, out_dir)
            for v in range(1, component_versions(component) + 1)
        ]
    return files
