"""Question to cited answer: retrieve, rerank, assemble numbered sources, generate, check.

The service yields events so the API can stream them: ``sources`` first (the UI can show them
while the answer is written), then ``token`` events, then ``done`` with the citation report.
"""

import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from qdrant_client import QdrantClient

from fcrag.config import Settings
from fcrag.embedding import Embedder
from fcrag.generation.citations import check_citations, format_locator
from fcrag.ingest.extract_params import Vocabulary
from fcrag.language import detect_language
from fcrag.llm.client import LLM, Message
from fcrag.retrieval.rerank import Reranker, rerank
from fcrag.retrieval.route import ParameterHit, ParameterStore, detect
from fcrag.retrieval.search import Filters, Hit, hybrid_search
from fcrag.units import display_unit

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
LANGUAGE_NAMES = {"en": "English", "de": "German"}
QUERY_MAX_TOKENS = 256


@lru_cache
def load_prompt(name: str = "answer") -> dict[str, Any]:
    prompt: dict[str, Any] = yaml.safe_load((PROMPTS_DIR / f"{name}.yaml").read_text("utf-8"))
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

    def rank(self, question: str, filters: Filters, timings: Timings | None = None) -> list[Hit]:
        """All hybrid-search candidates, reranked, best first (no cut-off, no threshold)."""
        t = timings or Timings()
        start = time.perf_counter()
        query = self.embedder.embed([question], max_tokens=QUERY_MAX_TOKENS)[0]
        t.embed_s = time.perf_counter() - start

        start = time.perf_counter()
        hits = hybrid_search(
            self.client,
            self.settings.qdrant_collection,
            query,
            filters,
            prefetch_limit=self.settings.prefetch_limit,
            limit=self.settings.prefetch_limit,
        )
        t.search_s = time.perf_counter() - start

        start = time.perf_counter()
        ranked = rerank(self.reranker, question, hits, top_k=len(hits), threshold=0.0)
        t.rerank_s = time.perf_counter() - start
        return ranked

    def retrieve(
        self, question: str, filters: Filters, timings: Timings | None = None
    ) -> list[Source]:
        """The evidence the LLM gets: the best ``rerank_top_k`` hits above the threshold."""
        ranked = self.rank(question, filters, timings)
        kept = [h for h in ranked if (h.rerank_score or 0.0) >= self.settings.rerank_threshold]
        return [Source.from_hit(i, h) for i, h in enumerate(kept[: self.settings.rerank_top_k], 1)]

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
        sources = self.parameter_sources(question) + self.retrieve(question, filters, timings)
        for n, source in enumerate(sources, 1):
            source.label = f"S{n}"
        yield {"type": "sources", "language": language, "sources": [asdict(s) for s in sources]}

        if not sources:
            text = prompt["not_found"][language]
            yield {"type": "token", "text": text}
            result = AnswerResult(question, language, text, found=False, timings=timings)
            yield {"type": "done", "result": asdict(result)}
            return
        if self.llm is None:
            raise RuntimeError(
                "No LLM configured: set an API key for FCRAG_LLM_MODEL or run a local model"
            )

        start = time.perf_counter()
        parts: list[str] = []
        for token in self.llm.stream(self.messages(question, language, sources)):
            parts.append(token)
            yield {"type": "token", "text": token}
        timings.generate_s = time.perf_counter() - start

        answer = "".join(parts)
        report = check_citations(answer, len(sources))
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
        )
        yield {"type": "done", "result": asdict(result)}

    def answer(self, question: str, filters: Filters | None = None) -> AnswerResult:
        """Non-streaming convenience wrapper, used by the CLI and the evaluation harness."""
        final: dict[str, Any] = {}
        for event in self.stream(question, filters):
            if event["type"] == "done":
                final = event["result"]
        sources = [Source(**s) for s in final.pop("sources")]
        timings = Timings(**final.pop("timings"))
        return AnswerResult(**final, sources=sources, timings=timings)
