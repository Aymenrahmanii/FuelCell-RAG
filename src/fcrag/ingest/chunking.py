"""Turn parsed elements into retrievable chunks.

Two strategies, switchable by config so the evaluation harness can compare them:

- ``section``: group consecutive text elements under the same heading, merge small sections,
  cap at ``max_tokens``. Tables, table rows, requirements, drawings and CAD parts always become
  chunks of their own.
- ``fixed``: the baseline; a sliding window of ``fixed_tokens`` with ``overlap_tokens`` over
  the running text, ignoring structure (structured elements still stay whole).

Token counts are estimated as characters / 4, which is close enough for bge-m3's tokenizer on
English and German technical text and keeps this module free of model dependencies.
"""

import math
import uuid
from dataclasses import dataclass, field
from typing import Any

from fcrag.models import Chunk, Element, SourceFile

CHUNK_NAMESPACE = uuid.UUID("6f1c2a4e-9d1b-4c7e-8a35-2f6b0e9d4c11")
STANDALONE_KINDS = {"table", "table_row", "requirement", "drawing", "cad_part"}


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: str = "section"
    max_tokens: int = 800
    min_tokens: int = 80
    fixed_tokens: int = 512
    overlap_tokens: int = 64
    contextual_headers: bool = True


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def chunk_id(doc_sha: str, index: int) -> str:
    """Deterministic point ID, so re-ingesting the same file overwrites the same points."""
    return str(uuid.uuid5(CHUNK_NAMESPACE, f"{doc_sha}:{index}"))


@dataclass
class _Draft:
    kind: str
    parts: list[str]
    heading_path: list[str]
    pages: list[int]
    locator: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(self.parts)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


REQUIREMENT_META = ("req_id", "parent", "links", "status", "type", "verification")


def _meta(element: Element) -> dict[str, Any]:
    """Structured fields worth keeping in the payload: requirement trace links and status."""
    if element.kind != "requirement" or not element.data:
        return {}
    return {k: element.data[k] for k in REQUIREMENT_META if element.data.get(k)}


def _page(element: Element) -> int | None:
    page = element.locator.get("page")
    return page if isinstance(page, int) else None


def _merge_locator(draft: _Draft) -> dict[str, Any]:
    locator = dict(draft.locator)
    pages = sorted(set(draft.pages))
    if pages:
        locator["page"] = pages[0]
    if len(pages) > 1:
        locator["pages"] = pages
        locator.pop("bbox", None)  # one bbox cannot describe a multi-page chunk
    return locator


def _windows(text: str, max_tokens: int, overlap_tokens: int) -> list[tuple[int, str]]:
    """Split text into ``(offset, piece)`` windows of about ``max_tokens``, preferring paragraph
    and sentence breaks."""
    max_chars, overlap_chars = max_tokens * 4, overlap_tokens * 4
    if len(text) <= max_chars:
        return [(0, text)]
    pieces: list[tuple[int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            window = text[start:end]
            for sep in ("\n\n", "\n", ". ", " "):
                cut = window.rfind(sep)
                if cut > max_chars // 2:
                    end = start + cut + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            pieces.append((start, piece))
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return pieces


def _split_long(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    return [piece for _, piece in _windows(text, max_tokens, overlap_tokens)]


def _section_drafts(elements: list[Element], cfg: ChunkingConfig) -> list[_Draft]:
    drafts: list[_Draft] = []
    current: _Draft | None = None

    def flush() -> None:
        nonlocal current
        if current is not None and current.parts:
            drafts.append(current)
        current = None

    for el in elements:
        page = _page(el)
        if el.kind in STANDALONE_KINDS:
            flush()
            drafts.append(
                _Draft(
                    el.kind,
                    [el.content],
                    el.heading_path,
                    [page] if page else [],
                    el.locator,
                    _meta(el),
                )
            )
            continue

        same_section = current is not None and current.heading_path == el.heading_path
        fits = (
            current is not None and current.tokens + estimate_tokens(el.content) <= cfg.max_tokens
        )
        small = current is not None and current.tokens < cfg.min_tokens
        if current is not None and fits and (same_section or small):
            if not same_section and el.heading_path:
                current.parts.append(el.heading_path[-1])
            current.parts.append(el.content)
            if page:
                current.pages.append(page)
            continue

        flush()
        current = _Draft("text", [el.content], el.heading_path, [page] if page else [], {})
    flush()
    return drafts


def _fixed_drafts(elements: list[Element], cfg: ChunkingConfig) -> list[_Draft]:
    drafts: list[_Draft] = []
    run: list[Element] = []

    def flush_run() -> None:
        if not run:
            return
        # Track which page each character offset came from, to locate each window.
        text = ""
        offsets: list[tuple[int, int | None]] = []
        for el in run:
            offsets.append((len(text), _page(el)))
            text += el.content + "\n\n"
        for pos, piece in _windows(text, cfg.fixed_tokens, cfg.overlap_tokens):
            page = next((p for off, p in reversed(offsets) if off <= pos), None)
            drafts.append(_Draft("text", [piece], run[0].heading_path, [page] if page else [], {}))
        run.clear()

    for el in elements:
        if el.kind in STANDALONE_KINDS:
            flush_run()
            page = _page(el)
            drafts.append(
                _Draft(
                    el.kind,
                    [el.content],
                    el.heading_path,
                    [page] if page else [],
                    el.locator,
                    _meta(el),
                )
            )
        else:
            run.append(el)
    flush_run()
    return drafts


def build_chunks(
    elements: list[Element], source: SourceFile, cfg: ChunkingConfig, *, is_latest: bool = True
) -> list[Chunk]:
    raw = (
        _section_drafts(elements, cfg)
        if cfg.strategy == "section"
        else _fixed_drafts(elements, cfg)
    )

    drafts: list[_Draft] = []
    for d in raw:
        pieces = _split_long(d.text, cfg.max_tokens, cfg.overlap_tokens)
        drafts.extend(
            _Draft(d.kind, [p], d.heading_path, d.pages, d.locator, d.meta) for p in pieces
        )

    title = source.title or source.doc_id
    chunks = []
    for i, d in enumerate(drafts):
        header = " > ".join([title, *d.heading_path])
        chunks.append(
            Chunk(
                chunk_id=chunk_id(source.sha256, i),
                doc_id=source.doc_id,
                doc_version=source.doc_version,
                doc_sha=source.sha256,
                is_latest=is_latest,
                title=title,
                system=source.system,
                doc_type=source.doc_type,
                language=source.language,
                kind=d.kind,
                text=d.text,
                embed_text=f"{header}\n\n{d.text}" if cfg.contextual_headers else d.text,
                heading_path=d.heading_path,
                locator=_merge_locator(d),
                meta=d.meta,
                allowed_groups=source.allowed_groups,
            )
        )
    return chunks
