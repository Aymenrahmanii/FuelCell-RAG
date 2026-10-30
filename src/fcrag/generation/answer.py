"""Question to cited answer: retrieve, rerank, assemble numbered sources, generate, check.

The service yields events so the API can stream them: ``sources`` first (the UI can show them
while the answer is written), then ``token`` events, then ``done`` with the citation report.
"""

import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import yaml
from qdrant_client import QdrantClient

from fcrag.config import Settings, get_settings
from fcrag.embedding import Embedder, Embedding
from fcrag.generation.citations import check_citations, format_locator, normalise_citations
from fcrag.ingest.extract_params import Vocabulary
from fcrag.language import detect_language
from fcrag.llm.client import LLM, Message
from fcrag.observability import start_trace
from fcrag.retrieval.rerank import Reranker, rerank
from fcrag.retrieval.route import ParameterHit, ParameterStore, detect
from fcrag.retrieval.search import Filters, Hit, hybrid_search
from fcrag.units import display_unit

LANGUAGE_NAMES = {"en": "English", "de": "German"}
QUERY_MAX_TOKENS = 256
REQUIREMENT_WORDS = re.compile(
    r"\b(requirements?|anforderung\w*|lastenheft|specification)\b|\bREQ-", re.IGNORECASE
)
EXTRA_REQUIREMENT_HITS = 3


@lru_cache
def load_prompt(name: str = "answer") -> dict[str, Any]:
    path = get_settings().prompts_dir / f"{name}.yaml"
    prompt: dict[str, Any] = yaml.safe_load(path.read_text("utf-8"))
    return prompt


@dataclass
class Source:
    label: str
    chunk_id: str
    doc_id: str
    title: str
    doc_version: int
    is_latest: bool
    kind: str
    locator: dict[str, Any]
    location: str
    text: str
    score: float

    @classmethod
    def from_hit(cls, n: int, hit: Hit) -> "Source":
        p = hit.payload
        locator = p.get("locator") or {}
        return cls(
            label=f"S{n}",
            chunk_id=hit.chunk_id,
            doc_id=p.get("doc_id", ""),
            title=p.get("title") or p.get("doc_id", ""),
            doc_version=p.get("doc_version", 1),
            is_latest=bool(p.get("is_latest", True)),
            kind=p.get("kind", "text"),
            locator=locator,
            location=format_locator(locator),
            text=hit.text,
            score=round(hit.rerank_score or 0.0, 4),
        )

    @classmethod
    def from_parameter(cls, hit: ParameterHit) -> "Source":
        r = hit.record
        unit = "" if r.unit == "-" else f" {display_unit(r.unit)}"
        condition = f" ({r.condition})" if r.condition else ""
        where = r.component or "system level"
        return cls(
            label="",
            chunk_id=f"param:{r.id}",
            doc_id=r.doc_id,
            title=hit.title,
            doc_version=r.doc_version,
            is_latest=hit.is_latest,
            kind="parameter",
            locator=r.locator,
            location=format_locator(r.locator),
            text=f"{r.system}, {where}: {r.label} = {r.value:g}{unit}{condition}",
            score=1.0,
        )

    def prompt_block(self) -> str:
        version = f"v{self.doc_version}" + (" (latest)" if self.is_latest else " (superseded)")
        where = f", {self.location}" if self.location else ""
        return f"[{self.label}] {self.title}, {version}{where}\n{self.text}"


def dedupe(sources: list[Source]) -> list[Source]:
    """Drop later sources pointing at the same place (a parameter record and the chunk it was
    extracted from); the first, usually the structured record, is kept."""
    seen: set[tuple[str, int, str]] = set()
    unique = []
    for source in sources:
        key = (source.doc_id, source.doc_version, source.location)
        if source.location and key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique


@dataclass
class Timings:
    embed_s: float = 0.0
    search_s: float = 0.0
    rerank_s: float = 0.0
    generate_s: float = 0.0


@dataclass
class AnswerResult:
    question: str
    language: str
    answer: str
    found: bool
    sources: list[Source] = field(default_factory=list)
    cited: list[int] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)
    uncited_sentences: list[str] = field(default_factory=list)
    prompt_version: str = ""
    model: str = ""
    timings: Timings = field(default_factory=Timings)
    trace_id: str | None = None


class RagService:
    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        reranker: Reranker,
        client: QdrantClient,
        llm: LLM | None,
        params: ParameterStore | None = None,
        vocabulary: Vocabulary | None = None,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.reranker = reranker
        self.client = client
        self.llm = llm
        self.params = params
        self.vocabulary = vocabulary

    def parameter_sources(self, question: str) -> list[Source]:
        """Exact records from the parameters table when the question names system and parameter."""
        if self.params is None or self.vocabulary is None:
            return []
        route = detect(question, self.vocabulary)
        if not route.is_parameter_query:
            return []
        return [Source.from_parameter(h) for h in self.params.lookup(route.systems, route.keys)]

    def scope(self, question: str, filters: Filters) -> Filters:
        """Limit retrieval to the systems a question names, unless the caller chose systems.

        "Is the System C requirement consistent with the parameter list?" otherwise ranks
        System A's pump datasheet above the System C requirement."""
        if filters.systems or filters.named_systems or self.vocabulary is None:
            return filters
        named = detect(question, self.vocabulary).systems
        return replace(filters, named_systems=named) if named else filters

    def rank(
        self,
        question: str,
        filters: Filters,
        timings: Timings | None = None,
        *,
        query: Embedding | None = None,
        limit: int | None = None,
    ) -> list[Hit]:
        """All hybrid-search candidates, reranked, best first (no cut-off, no threshold).
        Search and rerank times add up in ``timings`` across calls."""
        t = timings or Timings()
        filters = self.scope(question, filters)
        if query is None:
            start = time.perf_counter()
            query = self.embedder.embed([question], max_tokens=QUERY_MAX_TOKENS)[0]
            t.embed_s += time.perf_counter() - start

        start = time.perf_counter()
        hits = hybrid_search(
            self.client,
            self.settings.qdrant_collection,
            query,
            filters,
            prefetch_limit=limit or self.settings.prefetch_limit,
            limit=limit or self.settings.prefetch_limit,
        )
        t.search_s += time.perf_counter() - start

        start = time.perf_counter()
        ranked = rerank(self.reranker, question, hits, top_k=len(hits), threshold=0.0)
        t.rerank_s += time.perf_counter() - start
        return ranked

    def retrieve(
        self, question: str, filters: Filters, timings: Timings | None = None
    ) -> list[Source]:
        """The evidence the LLM gets: the best ``rerank_top_k`` hits above the threshold.

        A question about requirements also gets the best requirement chunks: without them,
        "does the requirement agree with the parameter sheet?" retrieves only the sheet, and the
        model answers about a requirement it never saw.
        """
        t = timings or Timings()
        start = time.perf_counter()
        query = self.embedder.embed([question], max_tokens=QUERY_MAX_TOKENS)[0]
        t.embed_s += time.perf_counter() - start

        threshold = self.settings.rerank_threshold
        ranked = self.rank(question, filters, t, query=query)
        kept = [h for h in ranked if (h.rerank_score or 0.0) >= threshold]
        kept = kept[: self.settings.rerank_top_k]
        if REQUIREMENT_WORDS.search(question) and "requirements" not in filters.doc_types:
            req_filters = replace(filters, doc_types=["requirements"])
            present = {h.chunk_id for h in kept}
            extra = [
                h
                for h in self.rank(question, req_filters, t, query=query, limit=20)
                if h.chunk_id not in present and (h.rerank_score or 0.0) >= threshold
            ]
            kept += extra[:EXTRA_REQUIREMENT_HITS]
        return [Source.from_hit(i, h) for i, h in enumerate(kept, 1)]

    def messages(self, question: str, language: str, sources: list[Source]) -> list[Message]:
        prompt = load_prompt()
        system = prompt["system"].format(language_name=LANGUAGE_NAMES[language])
        user = prompt["user"].format(
            sources="\n\n".join(s.prompt_block() for s in sources), question=question
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def stream(self, question: str, filters: Filters | None = None) -> Iterator[dict[str, Any]]:
        filters = filters or Filters()
        prompt = load_prompt()
        language = detect_language(question)
        timings = Timings()
        trace = start_trace(
            "rag.answer",
            as_type="chain",
            input={"question": question},
            metadata={"filters": asdict(filters), "language": language,
                      "prompt_version": prompt["version"]},
        )  # fmt: skip
        trace_id = getattr(trace, "trace_id", None)
        try:
            span = trace.start_observation(name="retrieve", as_type="retriever", input=question)
            structured = self.parameter_sources(question)
            sources = dedupe(structured + self.retrieve(question, filters, timings))
            for n, source in enumerate(sources, 1):
                source.label = f"S{n}"
            span.update(
                output=[f"[{s.label}] {s.title} v{s.doc_version} {s.location} ({s.score})"
                        for s in sources],
                metadata={"timings": asdict(timings), "structured_sources": len(structured)},
            ).end()  # fmt: skip
            yield {
                "type": "sources",
                "language": language,
                "trace_id": trace_id,
                "sources": [asdict(s) for s in sources],
            }

            if not sources:
                text = prompt["not_found"][language]
                yield {"type": "token", "text": text}
                result = AnswerResult(
                    question, language, text, found=False, timings=timings, trace_id=trace_id
                )
                trace.update(output=text, metadata={"found": False})
                yield {"type": "done", "result": asdict(result)}
                return
            if self.llm is None:
                raise RuntimeError(
                    "No LLM configured: set an API key for FCRAG_LLM_MODEL or run a local model"
                )

            messages = self.messages(question, language, sources)
            generation = trace.start_observation(
                name="generate", as_type="generation", model=self.llm.model, input=messages,
                metadata={"prompt_version": prompt["version"]},
            )  # fmt: skip
            start = time.perf_counter()
            parts: list[str] = []
            for token in self.llm.stream(messages):
                if not parts:
                    generation.update(completion_start_time=datetime.now(UTC))
                parts.append(token)
                yield {"type": "token", "text": token}
            timings.generate_s = time.perf_counter() - start
            answer = normalise_citations("".join(parts))
            generation.update(output=answer, model=self.llm.model).end()  # fallback may differ

            report = check_citations(answer, len(sources))
            trace.start_observation(
                name="check_citations", input=answer, output=asdict(report)
            ).end()
            result = AnswerResult(
                question=question,
                language=language,
                answer=answer,
                found=True,
                sources=sources,
                cited=report.cited,
                invalid_citations=report.invalid,
                uncited_sentences=report.uncited_sentences,
                prompt_version=prompt["version"],
                model=self.llm.model,
                timings=timings,
                trace_id=trace_id,
            )
            trace.update(output=answer, metadata={"found": True, "cited": report.cited,
                                                  "invalid_citations": report.invalid})  # fmt: skip
            yield {"type": "done", "result": asdict(result)}
        except Exception as exc:
            trace.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            trace.end()

    def answer(self, question: str, filters: Filters | None = None) -> AnswerResult:
        """Non-streaming convenience wrapper, used by the CLI and the evaluation harness."""
        final: dict[str, Any] = {}
        for event in self.stream(question, filters):
            if event["type"] == "done":
                final = event["result"]
        sources = [Source(**s) for s in final.pop("sources")]
        timings = Timings(**final.pop("timings"))
        return AnswerResult(**final, sources=sources, timings=timings)
