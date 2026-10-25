"""Requirements parser for ReqIF, CSV and DOCX exports.

Each requirement becomes one element with its ID, text, type, status, verification method and
links. Its parent's text is added as context, so a retrieved child still reads correctly.
Links written only in prose ("see also REQ-A-0007") are found by pattern.
"""

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from defusedxml import ElementTree as SafeET

from fcrag.ingest.parsers import register
from fcrag.models import Element, SourceFile

REQ_ID = re.compile(r"\b(?:REQ|SYS|SRS|SR)-[A-Z0-9]+-\d{2,5}\b|\b(?:REQ|SYS|SRS|SR)-\d{2,5}\b")

# Column / attribute names seen in real exports, mapped to our fields.
FIELD_NAMES = {
    "id": {"id", "reqid", "req id", "requirement id", "identifier", "key", "anforderungs-id"},
    "title": {"title", "name", "heading", "titel", "bezeichnung", "überschrift"},
    "text": {"text", "description", "requirement", "requirement text", "beschreibung",
             "anforderung", "anforderungstext"},
    "type": {"type", "category", "typ", "kategorie", "art"},
    "status": {"status", "state", "zustand"},
    "verification": {"verification", "verification method", "verifikation", "nachweis",
                     "nachweisart", "prüfmethode"},
    "parent": {"parent", "refines", "parent id", "übergeordnet", "verfeinert", "eltern-id"},
    "links": {"links", "related", "references", "verweise", "siehe auch"},
}  # fmt: skip


def _field(name: str) -> str | None:
    key = name.strip().lower()
    return next((f for f, names in FIELD_NAMES.items() if key in names), None)


@dataclass
class Req:
    req_id: str
    title: str = ""
    text: str = ""
    req_type: str = ""
    status: str = ""
    verification: str = ""
    parent: str | None = None
    links: list[str] = field(default_factory=list)
    section: list[str] = field(default_factory=list)

    def set(self, name: str, value: str) -> None:
        value = value.strip()
        if name == "title":
            self.title = value
        elif name == "text":
            self.text = value
        elif name == "type":
            self.req_type = value
        elif name == "status":
            self.status = value
        elif name == "verification":
            self.verification = value
        elif name == "parent":
            self.parent = value or None
        elif name == "links":
            self.links += [x for x in REQ_ID.findall(value) if x not in self.links]


def _elements(reqs: list[Req]) -> Iterator[Element]:
    by_id = {r.req_id: r for r in reqs}
    for r in reqs:
        prose = [x for x in REQ_ID.findall(r.text) if x not in (r.req_id, r.parent)]
        links = list(dict.fromkeys(r.links + prose))
        meta = "; ".join(
            f"{k}: {v}"
            for k, v in (("Type", r.req_type), ("Status", r.status),
                         ("Verification", r.verification), ("Refines", r.parent or ""),
                         ("Links", ", ".join(links)))
            if v
        )  # fmt: skip
        lines = [f"{r.req_id}: {r.title}".rstrip(": "), r.text]
        if meta:
            lines.append(meta)
        parent = by_id.get(r.parent or "")
        if parent:
            lines.append(f"Parent {parent.req_id} ({parent.title}): {parent.text}")
        yield Element(
            kind="requirement",
            content="\n".join(line for line in lines if line),
            heading_path=r.section,
            locator={"req_id": r.req_id},
            data={
                "req_id": r.req_id, "title": r.title, "text": r.text, "type": r.req_type,
                "status": r.status, "verification": r.verification, "parent": r.parent,
                "links": links,
            },
        )  # fmt: skip


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_reqif(data: bytes) -> list[Req]:
    root = SafeET.fromstring(data)
    names: dict[str, str] = {}
    for node in root.iter():
        if _local(node.tag).startswith("ATTRIBUTE-DEFINITION-"):
            names[node.get("IDENTIFIER", "")] = node.get("LONG-NAME", "")

    reqs: dict[str, Req] = {}
    for obj in (n for n in root.iter() if _local(n.tag) == "SPEC-OBJECT"):
        values: dict[str, str] = {}
        for av in (n for n in obj.iter() if _local(n.tag).startswith("ATTRIBUTE-VALUE-")):
            ref = next(
                (n.text for n in av.iter() if _local(n.tag).startswith("ATTRIBUTE-DEFINITION-")),
                None,
            )
            if ref is None:
                continue
            if av.get("THE-VALUE") is not None:
                text = av.get("THE-VALUE", "")
            else:  # XHTML values carry their text in child elements
                the_value = next((n for n in av if _local(n.tag) == "THE-VALUE"), None)
                text = (
                    " ".join("".join(the_value.itertext()).split()) if the_value is not None else ""
                )
            values[names.get(ref.strip(), ref.strip())] = text
        identifier = obj.get("IDENTIFIER", "")
        req = Req(req_id=next((v for k, v in values.items() if _field(k) == "id"), identifier))
        for key, value in values.items():
            name = _field(key)
            if name and name != "id":
                req.set(name, value)
        reqs[identifier] = req

    for rel in (n for n in root.iter() if _local(n.tag) == "SPEC-RELATION"):
        refs = {
            _local(part.tag): next(
                (n.text for n in part.iter() if _local(n.tag) == "SPEC-OBJECT-REF"), None
            )
            for part in rel
            if _local(part.tag) in {"SOURCE", "TARGET"}
        }
        source, target = reqs.get(refs.get("SOURCE") or ""), reqs.get(refs.get("TARGET") or "")
        if source and target:
            source.parent = target.req_id
    return list(reqs.values())


def parse_csv(text: str) -> list[Req]:
    sample = text[:4096]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    mapping = {col: _field(col) for col in reader.fieldnames or []}
    if "id" not in mapping.values():
        raise ValueError("CSV has no requirement ID column")
    reqs = []
    for row in reader:
        values: dict[str, str] = {}
        for column, value in row.items():
            name = mapping.get(column) if column else None
            if name:
                values[name] = value or ""
        if not values.get("id", "").strip():
            continue
        req = Req(req_id=values.pop("id").strip())
        for name, value in values.items():
            req.set(name, value)
        reqs.append(req)
    return reqs


def parse_docx(path: Any) -> list[Req]:
    """Requirement headings ("REQ-B-0001 Title"), text paragraphs, then a key/value table."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    reqs: list[Req] = []
    section: list[str] = []
    current: Req | None = None
    for child in doc.element.body.iterchildren():
        tag = _local(child.tag)
        if tag == "p":
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name if para.style is not None else "").lower()
            match = REQ_ID.match(text)
            if match:
                current = Req(req_id=match.group(0), title=text[match.end() :].strip(" :-–"))
                current.section = list(section)
                reqs.append(current)
            elif style.startswith("heading") or style == "title":
                section = [text]
                current = None
            elif current is not None:
                current.text = f"{current.text} {text}".strip()
        elif tag == "tbl" and current is not None:
            for row in Table(child, doc).rows:
                cells = [c.text.strip() for c in row.cells]
                if len(cells) >= 2 and (name := _field(cells[0])):
                    current.set(name, cells[1])
    return reqs


class RequirementsParser:
    supported_types = frozenset({".reqif", ".csv", ".docx", "text/csv"})

    def parse(self, file: SourceFile) -> Iterator[Element]:
        suffix = file.path.suffix.lower()
        if suffix == ".reqif":
            reqs = parse_reqif(file.path.read_bytes())
        elif suffix == ".docx":
            reqs = parse_docx(file.path)
        else:
            reqs = parse_csv(file.path.read_text(encoding="utf-8-sig"))
        yield from _elements(reqs)


register(RequirementsParser())
