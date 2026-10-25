"""Requirement specifications in three export formats: ReqIF (System A), DOCX (System B, German)
and semicolon CSV (System C).

Each system gets system-level requirements and component requirements that refine them. Some
links are only written in prose ("see also ..."), and one requirement per system deliberately
contradicts the parameter sheet, so conflict detection has something to find.
"""

import csv
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document as DocxDocument

from fcrag.datagen.common import (
    GeneratedFile,
    format_number,
    label,
    make_fact,
)
from fcrag.truth import Component, SystemTruth, TruthParameter
from fcrag.units import display_unit

REQIF_NS = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
VERIFICATION = {"stack": "Test", "air_compressor": "Test", "air_blower": "Test"}
STATUSES = ("approved", "approved", "approved", "in review", "draft")

# Requirement that contradicts the parameter sheet: (component id suffix, key, stated value)
CONFLICTS = {
    "A": ("STK", "coolant_outlet_temperature_max", 90.0),
    "B": ("STK", "cathode_inlet_pressure_rated", 250.0),
    "C": ("CLP", "coolant_flow_rated", 200.0),
}

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "max": "The {subject} shall not exceed a {label} of {value} {unit}{condition}.",
        "min": "The {subject} shall achieve a {label} of {value} {unit}{condition}.",
        "nominal": "The {subject} shall have a {label} of {value} {unit}{condition}.",
        "see_also": " See also {ref}.",
        "system": "fuel cell system",
        "title": "{system} requirements specification",
    },
    "de": {
        "max": "Das {subject} darf eine {label} von {value} {unit}{condition} nicht überschreiten.",
        "min": "Das {subject} muss eine {label} von {value} {unit}{condition} erreichen.",
        "nominal": "Das {subject} muss eine {label} von {value} {unit}{condition} aufweisen.",
        "see_also": " Siehe auch {ref}.",
        "system": "Brennstoffzellensystem",
        "title": "Lastenheft {system}",
    },
}
DE_SUBJECT = {
    "stack": "Stackmodul",
    "air_compressor": "Luftverdichtermodul",
    "air_blower": "Gebläsemodul",
    "humidifier": "Befeuchtermodul",
    "coolant_pump": "Kühlmittelpumpenmodul",
    "h2_recirculation": "Rezirkulationsmodul",
}


@dataclass
class Requirement:
    req_id: str
    title: str
    text: str
    req_type: str
    status: str
    verification: str
    parent: str | None
    component: Component | None
    param: TruthParameter
    stated_value: float
    links: list[str] = field(default_factory=list)


def _kind(key: str) -> str:
    if key.endswith("_max") or "max" in key.split("_"):
        return "max"
    if key.startswith(("cold_start", "design_lifetime", "rated_", "system_efficiency")):
        return "min"
    return "nominal"


def _req_type(key: str) -> str:
    if "temperature" in key or "pressure" in key:
        return "environmental" if "ambient" in key or "cold" in key else "operating limit"
    if key.startswith(("stack_mass", "stack_volume", "system_mass", "membrane", "pt_loading")):
        return "design"
    return "performance"


def build_requirements(system: SystemTruth, language: str) -> list[Requirement]:
    t = TEXT[language]
    code = system.code
    reqs: list[Requirement] = []
    by_key: dict[str, str] = {}

    def add(
        component: Component | None, param: TruthParameter, parent: str | None, value: float
    ) -> Requirement:
        n = len(reqs) + 1
        req_id = f"REQ-{code}-{n:04d}"
        if component is None:
            subject = t["system"]
        elif language == "de":
            subject = DE_SUBJECT[component.type]
        else:
            subject = component.name[0].lower() + component.name[1:]
        name = label(param, language)
        condition = f" ({param.condition})" if param.condition else ""
        text = t[_kind(param.key)].format(
            subject=subject,
            label=name if language == "de" else name[0].lower() + name[1:],
            value=format_number(value, language),
            unit=display_unit(param.unit),
            condition=condition,
        )
        req = Requirement(
            req_id=req_id,
            title=name,
            text=text,
            req_type=_req_type(param.key),
            status=STATUSES[n % len(STATUSES)],
            verification=VERIFICATION.get(component.type if component else "", "Analysis"),
            parent=parent,
            component=component,
            param=param,
            stated_value=value,
        )
        reqs.append(req)
        by_key.setdefault(param.key, req_id)
        return req

    for param in system.parameters:
        add(None, param, None, param.value)

    def parent_for(component: Component, key: str) -> str | None:
        if component.type == "stack" and key in {"rated_gross_power", "rated_current"}:
            return by_key.get("rated_net_power")
        if component.type == "stack":
            return by_key.get("design_lifetime")
        return by_key.get("system_efficiency_rated")

    conflict_component, conflict_key, conflict_value = CONFLICTS[code]
    for component in system.components:
        for param in component.parameters:
            is_conflict = component.id.endswith(conflict_component) and param.key == conflict_key
            req = add(
                component,
                param,
                parent_for(component, param.key),
                conflict_value if is_conflict else param.value,
            )
            # Some cross-references exist only in prose, the way real specs are written.
            if (
                param.key.startswith("coolant_outlet_temperature_max")
                and "ambient_temperature_max" in by_key
            ):
                ref = by_key["ambient_temperature_max"]
                req.text += t["see_also"].format(ref=ref)
                req.links.append(ref)
    return reqs


def _facts(system: SystemTruth, reqs: list[Requirement], out: GeneratedFile) -> None:
    for r in reqs:
        out.facts.append(
            make_fact(
                system, r.component, r.param, r.stated_value, r.param.unit, out,
                {"req_id": r.req_id}, truth_value=r.param.value,
            )
        )  # fmt: skip


def _out(system: SystemTruth, ext: str, language: str) -> GeneratedFile:
    doc_id = f"req-system-{system.code.lower()}"
    return GeneratedFile(
        file=f"{doc_id}.{ext}",
        doc_id=doc_id,
        doc_version=1,
        title=TEXT[language]["title"].format(system=system.system),
        system=system.system,
        doc_type="requirements",
        language=language,
    )


def write_reqif(system: SystemTruth, out_dir: Path) -> GeneratedFile:
    out = _out(system, "reqif", "en")
    reqs = build_requirements(system, "en")
    ET.register_namespace("", REQIF_NS)

    def el(parent: ET.Element, tag: str, **attrs: str) -> ET.Element:
        return ET.SubElement(parent, f"{{{REQIF_NS}}}{tag}", attrs)

    root = ET.Element(f"{{{REQIF_NS}}}REQ-IF")
    header = el(el(root, "THE-HEADER"), "REQ-IF-HEADER", IDENTIFIER=f"hdr-{out.doc_id}")
    el(header, "TITLE").text = out.title
    el(header, "CREATION-TIME").text = "2026-10-25T00:00:00Z"
    content = el(el(root, "CORE-CONTENT"), "REQ-IF-CONTENT")
    el(el(content, "DATATYPES"), "DATATYPE-DEFINITION-STRING",
       IDENTIFIER="DT-STR", **{"LONG-NAME": "String", "MAX-LENGTH": "4000"})  # fmt: skip
    spec_types = el(content, "SPEC-TYPES")
    sot = el(spec_types, "SPEC-OBJECT-TYPE", IDENTIFIER="SOT-REQ", **{"LONG-NAME": "Requirement"})
    attrs = el(sot, "SPEC-ATTRIBUTES")
    fields = ["ReqID", "Title", "Text", "Type", "Status", "Verification"]
    for name in fields:
        ad = el(attrs, "ATTRIBUTE-DEFINITION-STRING", IDENTIFIER=f"AD-{name}",
                **{"LONG-NAME": name})  # fmt: skip
        el(el(ad, "TYPE"), "DATATYPE-DEFINITION-STRING-REF").text = "DT-STR"
    el(spec_types, "SPEC-RELATION-TYPE", IDENTIFIER="SRT-REFINES", **{"LONG-NAME": "refines"})

    objects = el(content, "SPEC-OBJECTS")
    for r in reqs:
        obj = el(
            objects, "SPEC-OBJECT", IDENTIFIER=r.req_id, **{"LAST-CHANGE": "2026-10-25T00:00:00Z"}
        )
        el(el(obj, "TYPE"), "SPEC-OBJECT-TYPE-REF").text = "SOT-REQ"
        values = el(obj, "VALUES")
        for name, value in zip(
            fields, [r.req_id, r.title, r.text, r.req_type, r.status, r.verification], strict=True
        ):
            av = el(values, "ATTRIBUTE-VALUE-STRING", **{"THE-VALUE": value})
            el(el(av, "DEFINITION"), "ATTRIBUTE-DEFINITION-STRING-REF").text = f"AD-{name}"

    relations = el(content, "SPEC-RELATIONS")
    for n, r in enumerate((r for r in reqs if r.parent), 1):
        rel = el(relations, "SPEC-RELATION", IDENTIFIER=f"REL-{n:04d}")
        el(el(rel, "TYPE"), "SPEC-RELATION-TYPE-REF").text = "SRT-REFINES"
        el(el(rel, "SOURCE"), "SPEC-OBJECT-REF").text = r.req_id
        el(el(rel, "TARGET"), "SPEC-OBJECT-REF").text = r.parent

    spec = el(el(content, "SPECIFICATIONS"), "SPECIFICATION", IDENTIFIER=f"SPEC-{system.code}",
              **{"LONG-NAME": out.title})  # fmt: skip
    children = el(spec, "CHILDREN")
    for r in (r for r in reqs if not r.parent):
        hierarchy = el(children, "SPEC-HIERARCHY", IDENTIFIER=f"H-{r.req_id}")
        el(el(hierarchy, "OBJECT"), "SPEC-OBJECT-REF").text = r.req_id
        kids = [c for c in reqs if c.parent == r.req_id]
        if kids:
            sub = el(hierarchy, "CHILDREN")
            for c in kids:
                h = el(sub, "SPEC-HIERARCHY", IDENTIFIER=f"H-{c.req_id}")
                el(el(h, "OBJECT"), "SPEC-OBJECT-REF").text = c.req_id

    ET.indent(root)
    ET.ElementTree(root).write(out_dir / out.file, encoding="utf-8", xml_declaration=True)
    _facts(system, reqs, out)
    return out


def write_docx(system: SystemTruth, out_dir: Path) -> GeneratedFile:
    out = _out(system, "docx", "de")
    reqs = build_requirements(system, "de")
    doc = DocxDocument()
    doc.add_heading(out.title, level=0)
    doc.add_paragraph(
        "Dieses Lastenheft beschreibt die Anforderungen an das Brennstoffzellensystem. "
        "Untergeordnete Anforderungen verfeinern die Systemanforderungen."
    )
    doc.add_heading("1 Systemanforderungen", level=1)
    in_components = False
    for r in reqs:
        if r.parent and not in_components:
            doc.add_heading("2 Komponentenanforderungen", level=1)
            in_components = True
        doc.add_heading(f"{r.req_id} {r.title}", level=2)
        doc.add_paragraph(r.text)
        table = doc.add_table(rows=0, cols=2)
        table.style = "Table Grid"
        meta = [("Typ", r.req_type), ("Status", r.status), ("Verifikation", r.verification)]
        if r.parent:
            meta.append(("Verfeinert", r.parent))
        for key, value in meta:
            cells = table.add_row().cells
            cells[0].text, cells[1].text = key, value
    doc.save(str(out_dir / out.file))
    _facts(system, reqs, out)
    return out


def write_csv(system: SystemTruth, out_dir: Path) -> GeneratedFile:
    out = _out(system, "csv", "en")
    reqs = build_requirements(system, "en")
    # Semicolon-separated with a BOM: what an Excel export on a German workstation looks like.
    with (out_dir / out.file).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(
            ["ID", "Title", "Text", "Type", "Status", "Verification", "Parent", "Links"]
        )
        for r in reqs:
            writer.writerow(
                [r.req_id, r.title, r.text, r.req_type, r.status, r.verification,
                 r.parent or "", ",".join(r.links)]
            )  # fmt: skip
    _facts(system, reqs, out)
    return out


WRITERS = {"A": write_reqif, "B": write_docx, "C": write_csv}


def build_all(system: SystemTruth, out_dir: Path) -> list[GeneratedFile]:
    return [WRITERS[system.code](system, out_dir)]
