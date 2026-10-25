"""Document registry: one row per document version, tracking ingestion state."""

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Status = Literal["pending", "indexed", "failed", "quarantined"]


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    source_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    """``<doc_id>@v<version>``, see :attr:`fcrag.models.SourceFile.source_key`."""
    doc_id: Mapped[str] = mapped_column(String(200), index=True)
    doc_version: Mapped[int] = mapped_column(Integer, default=1)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(Text)
    doc_type: Mapped[str | None] = mapped_column(String(40))
    system: Mapped[str | None] = mapped_column(String(40))
    language: Mapped[str | None] = mapped_column(String(8))
    licence: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    element_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    indexed_sha256: Mapped[str | None] = mapped_column(String(64))
    """Hash of the file content currently in the index; differs from ``sha256`` until re-indexed."""
    duration_s: Mapped[float | None]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Feedback(Base):
    """User rating of an answer. Stored without user identifiers."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    rating: Mapped[int] = mapped_column(Integer)
    """+1 helpful, -1 not helpful."""
    comment: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ParameterRecord(Base):
    """Extracted parameter values, so exact lookups need no text search."""

    __tablename__ = "parameters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system: Mapped[str] = mapped_column(String(40), index=True)
    component: Mapped[str | None] = mapped_column(String(40))
    parameter: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(Text)
    value: Mapped[float]
    unit: Mapped[str] = mapped_column(String(20))
    value_norm: Mapped[float]
    unit_norm: Mapped[str] = mapped_column(String(20))
    condition: Mapped[str | None] = mapped_column(Text)
    doc_id: Mapped[str] = mapped_column(String(200), index=True)
    doc_version: Mapped[int] = mapped_column(Integer)
    locator: Mapped[dict[str, Any]] = mapped_column(JSON)
    method: Mapped[str] = mapped_column(String(20))
    source_text: Mapped[str] = mapped_column(Text, default="")
