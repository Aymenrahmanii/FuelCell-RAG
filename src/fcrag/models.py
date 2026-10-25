"""Schemas shared across ingestion, retrieval and evaluation.

Every parser emits :class:`Element` objects, so the rest of the pipeline never needs to know
which file format an element came from.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

ElementKind = Literal["text", "table", "table_row", "requirement", "drawing", "cad_part"]
DocType = Literal["report", "datasheet", "parameter_sheet", "requirements", "drawing", "cad"]


class SourceFile(BaseModel):
    """A file discovered in the source folder or bucket, identified by its content hash."""

    path: Path
    sha256: str
    mime_type: str
    doc_id: str
    doc_version: int = 1
    doc_type: DocType | None = None
    system: str | None = None
    licence: str | None = None


class Element(BaseModel):
    """One parsed unit of a document, before chunking."""

    kind: ElementKind
    content: str
    """Text the model will read."""
    heading_path: list[str] = Field(default_factory=list)
    """For example ``["3 Operating limits", "3.2 Temperatures"]``."""
    locator: dict[str, Any] = Field(default_factory=dict)
    """Page and bbox, sheet and cell range, ``req_id`` or ``part_id``: whatever a citation needs."""
    data: dict[str, Any] | None = None
    """Structured payload such as table rows or extracted parameters."""


class Parser(Protocol):
    """Interface every file-type parser implements. Adding a format means one new class."""

    supported_types: set[str]
    """MIME types or lower-case extensions (``".xlsx"``) this parser handles."""

    def parse(self, file: SourceFile) -> Iterator[Element]: ...


class Chunk(BaseModel):
    """A retrievable unit stored as one Qdrant point."""

    chunk_id: str
    doc_id: str
    doc_version: int
    is_latest: bool
    system: str | None
    doc_type: DocType | None
    language: str | None
    kind: ElementKind
    text: str
    heading_path: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)
    allowed_groups: list[str] = Field(default_factory=list)


class Parameter(BaseModel):
    """A validated parameter record extracted from a table row or sentence."""

    system: str
    component: str
    parameter: str
    value: float
    unit: str
    condition: str | None = None
    doc_id: str
    doc_version: int
    locator: dict[str, Any]
