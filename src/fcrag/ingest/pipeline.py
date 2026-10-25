"""Ingestion pipeline: register, parse, enrich, chunk, embed, index, report.

Every stage is idempotent. A file whose content hash is already indexed is skipped; a file that
fails is retried on the next run and quarantined after ``max_attempts`` failures.
"""

import logging
import time
from dataclasses import dataclass
from typing import Literal

from qdrant_client import QdrantClient
from sqlalchemy import Engine, delete, func, select

import fcrag.ingest.parsers.excel
import fcrag.ingest.parsers.pdf
import fcrag.ingest.parsers.requirements
import fcrag.ingest.parsers.step  # noqa: F401  (importing registers the parsers)
from fcrag.config import Settings
from fcrag.db.models import Document, ParameterRecord
from fcrag.db.session import session_scope
from fcrag.embedding import Embedder
from fcrag.ingest import index
from fcrag.ingest.cache import ElementCache
from fcrag.ingest.chunking import ChunkingConfig, build_chunks
from fcrag.ingest.extract_params import Vocabulary, extract_parameters
from fcrag.ingest.parsers import parser_for, release_models
from fcrag.language import detect_language
from fcrag.models import Element, SourceFile

log = logging.getLogger(__name__)

Outcome = Literal["indexed", "skipped", "failed", "quarantined"]


@dataclass
class IngestResult:
    source_key: str
    outcome: Outcome
    elements: int = 0
    chunks: int = 0
    parameters: int = 0
    seconds: float = 0.0
    error: str | None = None


def chunking_config(s: Settings) -> ChunkingConfig:
    return ChunkingConfig(
        strategy=s.chunk_strategy,
        max_tokens=s.chunk_max_tokens,
        min_tokens=s.chunk_min_tokens,
        fixed_tokens=s.chunk_fixed_tokens,
        overlap_tokens=s.chunk_overlap_tokens,
        contextual_headers=s.contextual_headers,
    )


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        client: QdrantClient,
        engine: Engine,
        cache: ElementCache | None = None,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.client = client
        self.engine = engine
        self.collection = settings.qdrant_collection
        self.vocabulary = Vocabulary.from_truth(settings.systems_dir, settings.synonyms_path)
        self.cache = cache

    def run(self, files: list[SourceFile], *, force: bool = False) -> list[IngestResult]:
        """Two phases, so parsing and embedding models never share the GPU:
        1. parse every file that needs work (cached by content hash), then release the parsers;
        2. enrich, extract, chunk, embed and index.
        """
        index.ensure_collection(self.client, self.collection)
        plan = []
        for sf in files:
            needs_work, latest = self._register(sf)
            plan.append((sf, needs_work or force, latest))

        parsed: dict[str, list[Element] | Exception] = {}
        parse_s: dict[str, float] = {}
        todo = [sf for sf, work, _ in plan if work]
        for n, sf in enumerate(todo, 1):
            start = time.perf_counter()
            parsed[sf.source_key] = self._parse(sf)
            parse_s[sf.source_key] = time.perf_counter() - start
            log.info("parsed [%d/%d] %s (%.1fs)", n, len(todo), sf.source_key,
                     parse_s[sf.source_key])  # fmt: skip
        release_models()

        results = []
        for n, (sf, work, latest) in enumerate(plan, 1):
            if not work:
                result = IngestResult(sf.source_key, "skipped")
            else:
                key = sf.source_key
                result = self._index(sf, parsed[key], latest, parse_s[key])
            log.info(
                "[%d/%d] %-9s %s (%d elements, %d chunks, %d parameters, %.1fs)%s",
                n, len(files), result.outcome, result.source_key, result.elements,
                result.chunks, result.parameters, result.seconds,
                f": {result.error}" if result.error else "",
            )  # fmt: skip
            results.append(result)
        return results

    def _parse(self, sf: SourceFile) -> list[Element] | Exception:
        try:
            cached = self.cache.get(sf.sha256) if self.cache else None
            if cached is not None:
                return cached
            elements = list(parser_for(sf).parse(sf))
            if not elements:
                raise ValueError("parser produced no elements")
            if self.cache:
                self.cache.put(sf.sha256, elements)
            return elements
        except Exception as exc:
            return exc

    def _register(self, sf: SourceFile) -> tuple[bool, int]:
        """Upsert the registry row. Returns (needs_work, latest_version_of_this_doc)."""
        with session_scope(self.engine) as session:
            row = session.get(Document, sf.source_key)
            if row is None:
                row = Document(source_key=sf.source_key, attempts=0, status="pending")
                session.add(row)
            elif row.sha256 != sf.sha256:
                row.attempts = 0  # new content gets fresh retries
            row.doc_id, row.doc_version = sf.doc_id, sf.doc_version
            row.path = sf.path.as_posix()  # portable between Windows hosts and Linux containers
            row.sha256, row.mime_type, row.title = sf.sha256, sf.mime_type, sf.title
            row.doc_type, row.system, row.licence = sf.doc_type, sf.system, sf.licence
            done = row.status == "indexed" and row.indexed_sha256 == sf.sha256
            quarantined = row.status == "quarantined"
            session.flush()
            latest = session.scalar(
                select(func.max(Document.doc_version)).where(Document.doc_id == sf.doc_id)
            )
        return not (done or quarantined), max(latest or 1, sf.doc_version)

    def _index(
        self,
        sf: SourceFile,
        parsed: list[Element] | Exception,
        latest_version: int,
        parse_s: float,
    ) -> IngestResult:
        start = time.perf_counter() - parse_s
        if isinstance(parsed, Exception):
            return self._fail(sf, parsed, parse_s)
        elements = parsed
        try:
            if sf.language is None:
                sample = " ".join(e.content for e in elements[:40])
                sf = sf.model_copy(update={"language": detect_language(sample)})
            parameters = extract_parameters(self.vocabulary, sf, elements)
            chunks = build_chunks(
                elements,
                sf,
                chunking_config(self.settings),
                is_latest=sf.doc_version >= latest_version,
            )
            embeddings = self.embedder.embed([c.embed_text for c in chunks])
            index.upsert_chunks(self.client, self.collection, chunks, embeddings)
            index.delete_stale(self.client, self.collection, sf.doc_id, sf.doc_version, sf.sha256)
            index.mark_latest(self.client, self.collection, sf.doc_id, latest_version)
        except Exception as exc:
            return self._fail(sf, exc, time.perf_counter() - start)

        seconds = time.perf_counter() - start
        with session_scope(self.engine) as session:
            row = session.get_one(Document, sf.source_key)
            row.status, row.error, row.attempts = "indexed", None, 0
            row.language, row.indexed_sha256 = sf.language, sf.sha256
            row.element_count, row.chunk_count, row.duration_s = len(elements), len(chunks), seconds
            session.execute(
                delete(ParameterRecord).where(
                    ParameterRecord.doc_id == sf.doc_id,
                    ParameterRecord.doc_version == sf.doc_version,
                )
            )
            session.add_all(ParameterRecord(**p.model_dump()) for p in parameters)
        return IngestResult(
            sf.source_key, "indexed", len(elements), len(chunks), len(parameters), seconds
        )

    def _fail(self, sf: SourceFile, exc: Exception, seconds: float) -> IngestResult:
        log.exception("ingestion failed for %s", sf.source_key)
        error = f"{type(exc).__name__}: {exc}"[:2000]
        with session_scope(self.engine) as session:
            row = session.get_one(Document, sf.source_key)
            row.attempts += 1
            row.status = "quarantined" if row.attempts >= self.settings.max_attempts else "failed"
            row.error, row.duration_s = error, seconds
            outcome: Outcome = "quarantined" if row.status == "quarantined" else "failed"
        return IngestResult(sf.source_key, outcome, seconds=seconds, error=error)


def ingest_all(
    settings: Settings,
    *,
    force: bool = False,
    only: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Discover and ingest everything under ``settings.source_dirs``; used by CLI and worker."""
    import fnmatch

    from fcrag.db.session import get_engine
    from fcrag.embedding import get_embedder
    from fcrag.ingest.discover import discover

    files = discover(settings.source_dirs, settings.sources_manifest)
    if only:  # globs on doc_id, e.g. ["ps-*", "req-*"]
        files = [f for f in files if any(fnmatch.fnmatch(f.doc_id, g) for g in only)]
    if limit:
        files = files[:limit]
    cache = ElementCache(settings.element_cache_dir) if settings.element_cache_dir else None
    pipeline = Pipeline(settings, get_embedder(), index.get_client(), get_engine(), cache)
    counts: dict[str, int] = {"chunks": 0}
    for result in pipeline.run(files, force=force):
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
        counts["chunks"] += result.chunks
    return counts
