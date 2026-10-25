"""Read a STEP assembly with CadQuery in a separate process and print it as JSON.

OpenCascade's native libraries clash with docling-parse's when both load into one process on
Windows ("DLL load failed"), so the STEP parser never imports CadQuery itself; it runs
``python -m fcrag.ingest.parsers.step_geometry <file>`` instead.
Exit code 3 means CadQuery is not installed.
"""

import json
import sys
from typing import Any

NO_CADQUERY = 3


def read(path: str) -> dict[str, Any]:
    import cadquery as cq

    def convert(assy: Any) -> dict[str, Any]:
        node: dict[str, Any] = {"name": assy.name, "size_mm": None, "volume_mm3": None}
        if assy.obj is not None:
            shape: Any = assy.obj if isinstance(assy.obj, cq.Shape) else assy.obj.val()
            box = shape.BoundingBox()
            node["size_mm"] = [round(box.xlen, 1), round(box.ylen, 1), round(box.zlen, 1)]
            node["volume_mm3"] = round(shape.Volume(), 1)
        node["children"] = [convert(c) for c in assy.children]
        return node

    return convert(cq.Assembly.importStep(path))


def main() -> None:
    try:
        import cadquery  # noqa: F401
    except ImportError:
        sys.exit(NO_CADQUERY)
    json.dump(read(sys.argv[1]), sys.stdout)


if __name__ == "__main__":
    main()
