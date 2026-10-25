"""Parsed-element cache keyed by file content hash.

Parsing is the slow stage (Docling layout and table models). Caching its output means
re-chunking or re-embedding experiments never re-parse, and a crashed run resumes cheaply.
Bump ``ELEMENTS_VERSION`` when a parser's output format changes.
"""

import json
from pathlib import Path

from fcrag.models import Element

ELEMENTS_VERSION = "1"


class ElementCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, sha256: str) -> Path:
        return self.root / f"{sha256}.v{ELEMENTS_VERSION}.jsonl"

    def get(self, sha256: str) -> list[Element] | None:
        path = self._path(sha256)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as f:
            return [Element.model_validate_json(line) for line in f if line.strip()]

    def put(self, sha256: str, elements: list[Element]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._path(sha256).with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for element in elements:
                f.write(json.dumps(element.model_dump(mode="json"), ensure_ascii=False) + "\n")
        tmp.replace(self._path(sha256))
