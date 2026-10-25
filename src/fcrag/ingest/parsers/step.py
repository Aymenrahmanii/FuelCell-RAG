"""STEP parser: assembly tree, part names, bounding boxes and volumes.

With CadQuery/OpenCascade installed, geometry is read too. Without it, the assembly tree still
comes from the STEP text itself: PRODUCT entities carry the names and
NEXT_ASSEMBLY_USAGE_OCCURRENCE entities link parents to children.

Each part becomes one ``cad_part`` element, plus one summary element for the whole assembly.
"""

import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fcrag.ingest.parsers import register
from fcrag.models import Element, SourceFile

ENTITY = re.compile(r"#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*?)\)\s*;\s*$", re.MULTILINE | re.DOTALL)
REF = re.compile(r"#(\d+)")
STRING = re.compile(r"'((?:[^']|'')*)'")


@dataclass
class Node:
    name: str
    children: list["Node"] = field(default_factory=list)
    size_mm: tuple[float, float, float] | None = None
    volume_mm3: float | None = None

    def walk(self, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], "Node"]]:
        yield path, self
        for child in self.children:
            yield from child.walk((*path, self.name))


def tree_from_text(text: str) -> list[Node]:
    """Assembly roots from the STEP text, without a CAD kernel."""
    entities = {int(m.group(1)): (m.group(2), m.group(3)) for m in ENTITY.finditer(text)}
    product_name = {
        i: (STRING.findall(args) or [""])[1 if len(STRING.findall(args)) > 1 else 0]
        for i, (kind, args) in entities.items()
        if kind == "PRODUCT"
    }
    formation_product = {
        i: int(REF.findall(args)[0])
        for i, (kind, args) in entities.items()
        if kind.startswith("PRODUCT_DEFINITION_FORMATION") and REF.findall(args)
    }
    definition_name: dict[int, str] = {}
    for i, (kind, args) in entities.items():
        if kind == "PRODUCT_DEFINITION" and REF.findall(args):
            product = formation_product.get(int(REF.findall(args)[0]))
            if product in product_name:
                definition_name[i] = product_name[product]
    nodes = {i: Node(name) for i, name in definition_name.items()}
    children: set[int] = set()
    for kind, args in entities.values():
        if kind == "NEXT_ASSEMBLY_USAGE_OCCURRENCE":
            refs = [int(r) for r in REF.findall(args)]
            if len(refs) >= 2 and refs[0] in nodes and refs[1] in nodes:
                nodes[refs[0]].children.append(nodes[refs[1]])
                children.add(refs[1])
    return [n for i, n in nodes.items() if i not in children]


def tree_from_cad(path: Path) -> list[Node]:
    """Assembly roots with geometry, read by CadQuery in a child process (see step_geometry)."""
    from fcrag.ingest.parsers.step_geometry import NO_CADQUERY

    result = subprocess.run(
        [sys.executable, "-m", "fcrag.ingest.parsers.step_geometry", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode == NO_CADQUERY:
        raise ImportError("cadquery is not installed")
    if result.returncode != 0:
        raise RuntimeError(f"STEP geometry failed: {result.stderr.strip()[-500:]}")

    def convert(raw: dict[str, Any]) -> Node:
        size = raw.get("size_mm")
        return Node(
            name=raw["name"],
            children=[convert(c) for c in raw.get("children", [])],
            size_mm=(size[0], size[1], size[2]) if size else None,
            volume_mm3=raw.get("volume_mm3"),
        )

    return [convert(json.loads(result.stdout))]


def _describe(path: tuple[str, ...], node: Node) -> str:
    where = " > ".join(path) if path else "top level"
    parts = [f"Part {node.name} in assembly {where}."]
    if node.children:
        parts = [f"Assembly {node.name} ({where}) contains: "
                 + ", ".join(c.name for c in node.children) + "."]  # fmt: skip
    if node.size_mm:
        w, h, t = node.size_mm
        parts.append(f"Bounding box {w:g} x {h:g} x {t:g} mm.")
    if node.volume_mm3:
        parts.append(f"Volume {node.volume_mm3 / 1e6:.3g} L.")
    return " ".join(parts)


class StepParser:
    supported_types = frozenset({".step", ".stp", "model/step"})

    def parse(self, file: SourceFile) -> Iterator[Element]:
        try:
            roots = tree_from_cad(file.path)
        except ImportError:  # no CAD kernel: tree only
            roots = tree_from_text(file.path.read_text(encoding="utf-8", errors="replace"))
        for root in roots:
            leaves = [n for _, n in root.walk() if not n.children]
            summary = f"STEP assembly {root.name}: {len(leaves)} parts. Tree: " + "; ".join(
                f"{n.name} -> {', '.join(c.name for c in n.children)}"
                for _, n in root.walk()
                if n.children
            )
            if root.size_mm:
                summary += " Overall size {:g} x {:g} x {:g} mm.".format(*root.size_mm)
            yield Element(kind="cad_part", content=summary, heading_path=[root.name],
                          locator={"part_id": root.name})  # fmt: skip
            for path, node in root.walk():
                if node is root:
                    continue
                yield Element(
                    kind="cad_part",
                    content=_describe(path, node),
                    heading_path=list(path),
                    locator={"part_id": node.name},
                    data={
                        "part_id": node.name,
                        "parent": path[-1] if path else None,
                        "children": [c.name for c in node.children],
                        "size_mm": node.size_mm,
                        "volume_mm3": node.volume_mm3,
                    },
                )


register(StepParser())
