"""Does a retrieved chunk count as a gold source? Matches on document, version and locator."""

from typing import Any

from openpyxl.utils.cell import range_boundaries


def _cells_overlap(a: str, b: str) -> bool:
    a_col1, a_row1, a_col2, a_row2 = range_boundaries(a)
    b_col1, b_row1, b_col2, b_row2 = range_boundaries(b)
    return bool(
        a_col1 is not None and b_col1 is not None
        and a_row1 is not None and b_row1 is not None
        and a_col2 is not None and b_col2 is not None
        and a_row2 is not None and b_row2 is not None
        and a_col1 <= b_col2 and b_col1 <= a_col2
        and a_row1 <= b_row2 and b_row1 <= a_row2
    )  # fmt: skip


def locator_matches(chunk: dict[str, Any], gold: dict[str, Any]) -> bool:
    if "req_id" in gold:
        return bool(chunk.get("req_id") == gold["req_id"])
    if "part_id" in gold:
        return bool(chunk.get("part_id") == gold["part_id"])
    if "sheet" in gold:
        return chunk.get("sheet") == gold["sheet"] and (
            "cells" not in gold
            or "cells" not in chunk
            or _cells_overlap(str(chunk["cells"]), str(gold["cells"]))
        )
    if "page" in gold:
        pages = chunk.get("pages") or ([chunk["page"]] if "page" in chunk else [])
        return gold["page"] in pages
    return True


def matches(payload: dict[str, Any], gold: dict[str, Any]) -> bool:
    """``gold`` has ``doc_id`` and optionally ``doc_version`` and ``locator``."""
    if payload.get("doc_id") != gold["doc_id"]:
        return False
    if gold.get("doc_version") is not None and payload.get("doc_version") != gold["doc_version"]:
        return False
    locator = gold.get("locator")
    return locator_matches(payload.get("locator") or {}, locator) if locator else True
