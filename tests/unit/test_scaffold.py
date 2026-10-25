from collections.abc import Iterator
from pathlib import Path

import pytest

from fcrag.config import Settings
from fcrag.ingest import parsers
from fcrag.models import Element, SourceFile


class _CsvParser:
    def __init__(self) -> None:
        self.supported_types = frozenset({".csv", "text/csv"})

    def parse(self, file: SourceFile) -> Iterator[Element]:
        yield Element(kind="table_row", content="x", locator={"row": 1})


def _file(name: str, mime: str) -> SourceFile:
    return SourceFile(path=Path(name), sha256="0" * 64, mime_type=mime, doc_id="d")


def test_parser_routing_by_extension_and_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parsers, "_REGISTRY", [])
    csv = parsers.register(_CsvParser())
    assert parsers.parser_for(_file("reqs.CSV", "application/octet-stream")) is csv
    assert parsers.parser_for(_file("export", "text/csv")) is csv
    with pytest.raises(LookupError, match=r"plate\.step"):
        parsers.parser_for(_file("plate.step", "model/step"))


def test_restricted_mode_switches_to_local_llm() -> None:
    assert Settings(restricted_mode=True, _env_file=None).active_llm_model.startswith("ollama/")
    assert Settings(_env_file=None).active_llm_model.startswith("groq/")
