"""STEP assemblies of each system's stack (CadQuery), sized from the truth values.

The cell block's footprint follows the active area and its length the cell count times the
cell pitch. Part names are short and cryptic, as in real CAD exports; descriptions exist only
in the assembly tree, which is exactly the "little semantics" problem the parser must handle.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from fcrag.datagen.common import GeneratedFile
from fcrag.truth import SystemTruth

log = logging.getLogger(__name__)

CELL_PITCH_MM = {"A": 1.1, "B": 1.4, "C": 1.8}
"""Repeat-unit thickness: thin metal plates (A), graphite composite (B and C)."""
ASPECT = 2.5
"""Active area width-to-height ratio."""
MARGIN_MM = 20.0
"""Seal and manifold margin around the active area."""


@dataclass(frozen=True)
class Part:
    name: str
    """Cryptic CAD name, e.g. ``EP-02``."""
    description: str
    assembly: str
    """Sub-assembly the part belongs to (empty for the top level)."""
    size_mm: tuple[float, float, float]
    """Bounding box: width, height, thickness along the stack axis."""
    count: int = 1


def plate_size(system: SystemTruth) -> tuple[float, float]:
    """Outer plate width and height in mm, from the active area."""
    area_mm2 = system.lookup("active_area", f"{system.code}-STK").value * 100
    height = (area_mm2 / ASPECT) ** 0.5
    return round(height * ASPECT + 2 * MARGIN_MM, 1), round(height + 2 * MARGIN_MM, 1)


def stack_parts(system: SystemTruth) -> list[Part]:
    width, height = plate_size(system)
    cells = int(system.lookup("cell_count", f"{system.code}-STK").value)
    block = round(cells * CELL_PITCH_MM[system.code], 1)
    parts: list[Part] = []
    for side, n in (("dry", 1), ("wet", 2)):
        sub = f"EPA-0{n}"
        parts += [
            Part(f"EP-0{n}", f"end plate, {side} side", sub, (width + 20, height + 20, 25.0)),
            Part(f"INS-0{n}", f"insulation plate, {side} side", sub, (width, height, 5.0)),
            Part(
                f"CC-0{n}", f"current collector, {side} side", sub, (width - 10, height - 10, 2.0)
            ),
        ]
    parts += [
        Part("CB-01", f"cell block, {cells} cells", "", (width, height, block)),
        Part("TR-01", "tie rod M10", "", (10.0, 10.0, block + 2 * (25 + 5 + 2) + 40), count=4),
        Part("MF-01", "media manifold block", "", (60.0, height, 40.0)),
    ]
    return parts


def build_step(system: SystemTruth, out_dir: Path) -> GeneratedFile:
    import cadquery as cq

    doc_id = f"cad-stack-{system.code.lower()}"
    out = GeneratedFile(
        file=f"{doc_id}.step",
        doc_id=doc_id,
        doc_version=1,
        title=f"{system.system} stack assembly (STEP)",
        system=system.system,
        doc_type="cad",
        language="en",
    )
    parts = stack_parts(system)
    plate_w, plate_h = plate_size(system)
    corners = [
        (sx * (plate_w / 2 + 15), sy * (plate_h / 2 + 15)) for sx in (-1, 1) for sy in (-1, 1)
    ]
    top = cq.Assembly(name=f"{system.code}-STK-ASM")
    subs = {p.assembly: cq.Assembly(name=p.assembly) for p in parts if p.assembly}
    z = 0.0
    for part in parts:
        w, h, t = part.size_mm
        for i in range(part.count):
            name = part.name if part.count == 1 else f"{part.name}.{i + 1}"
            if part.name.startswith("TR"):  # tie rods at the end plate corners
                shape = cq.Workplane("XY").circle(w / 2).extrude(t)
                loc = cq.Location((*corners[i], -20))
            elif part.name.startswith("MF"):  # manifold on the dry-side end plate
                shape = cq.Workplane("XY").box(w, h, t, centered=(True, True, False))
                loc = cq.Location((plate_w / 2 - w, 0, -t))
            else:
                shape = cq.Workplane("XY").box(w, h, t, centered=(True, True, False))
                loc = cq.Location((0, 0, z))
            target = subs[part.assembly] if part.assembly else top
            target.add(shape, name=name, loc=loc)
        if not part.name.startswith(("TR", "MF")):
            z += t
    for sub in subs.values():
        top.add(sub, name=sub.name)
    top.export(str(out_dir / out.file))
    return out


def build_all(system: SystemTruth, out_dir: Path) -> list[GeneratedFile]:
    """STEP files need the optional ``cad`` extra (CadQuery); without it they are skipped."""
    try:
        import cadquery  # noqa: F401
    except ImportError:
        log.warning("CadQuery not installed (uv sync --extra cad): skipping STEP files")
        return []
    return [build_step(system, out_dir)]
