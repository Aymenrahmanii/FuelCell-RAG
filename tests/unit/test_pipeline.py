"""End-to-end ingestion and answering with fakes: SQLite registry, in-memory Qdrant."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models
from sqlalchemy import Engine, create_engine

from fcrag.config import Settings
from fcrag.db.models import Base, Document
from fcrag.db.session import session_scope
from fcrag.generation.answer import RagService
from fcrag.ingest import parsers
from fcrag.ingest.discover import sha256_file
from fcrag.ingest.pipeline import Pipeline
from fcrag.models import SourceFile
from fcrag.retrieval.search import Filters
from tests.fakes import FakeEmbedder, LineParser, OverlapReranker, ScriptedLLM

DATASHEET_V1 = """# 3 Operating limits
The maximum coolant outlet temperature of System B is 90 °C.
# 4 Materials
The bipolar plates are made of expanded graphite.
"""
DATASHEET_V2 = DATASHEET_V1.replace("90 °C", "85 °C")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None, qdrant_collection="test", chunk_min_tokens=1, rerank_threshold=0.3
    )


@pytest.fixture
def engine() -> Engine:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client() -> QdrantClient:
    return QdrantClient(":memory:")


@pytest.fixture(autouse=True)
def line_parser(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(parsers, "_REGISTRY", [LineParser()])
    yield


@pytest.fixture
def pipeline(settings: Settings, engine: Engine, client: QdrantClient) -> Pipeline:
    return Pipeline(settings, FakeEmbedder(), client, engine)


def source(path: Path, content: str, version: int = 1) -> SourceFile:
    path.write_text(content, encoding="utf-8")
    return SourceFile(
        path=path,
        sha256=sha256_file(path),
        mime_type="text/plain",
        doc_id="ds-stack-b",
        doc_version=version,
        system="System B",
        doc_type="datasheet",
        title="Stack datasheet B",
    )


def points(client: QdrantClient) -> list[models.Record]:
    return client.scroll("test", limit=100, with_payload=True)[0]


def test_ingest_then_skip_unchanged(
    pipeline: Pipeline, client: QdrantClient, tmp_path: Path
) -> None:
    sf = source(tmp_path / "ds.txt", DATASHEET_V1)
    first = pipeline.run([sf])[0]
    assert first.outcome == "indexed"
    assert first.chunks == len(points(client)) == 2
    assert {p.payload["language"] for p in points(client) if p.payload} == {"en"}

    assert pipeline.run([sf])[0].outcome == "skipped"


def test_changed_content_replaces_stale_chunks(
    pipeline: Pipeline, client: QdrantClient, tmp_path: Path
) -> None:
    path = tmp_path / "ds.txt"
    pipeline.run([source(path, DATASHEET_V1)])
    pipeline.run([source(path, DATASHEET_V2 + "Extra line.\n")])
    texts = [p.payload["text"] for p in points(client) if p.payload]
    assert not any("90 °C" in t for t in texts)
    assert any("85 °C" in t for t in texts)


def test_new_version_flips_is_latest(
    pipeline: Pipeline, client: QdrantClient, tmp_path: Path
) -> None:
    pipeline.run([source(tmp_path / "v1.txt", DATASHEET_V1, version=1)])
    pipeline.run([source(tmp_path / "v2.txt", DATASHEET_V2, version=2)])
    latest = {p.payload["doc_version"]: p.payload["is_latest"] for p in points(client) if p.payload}
    assert latest == {1: False, 2: True}


def test_failures_retry_then_quarantine(pipeline: Pipeline, engine: Engine, tmp_path: Path) -> None:
    sf = source(tmp_path / "bad.txt", "!fail\n")
    outcomes = [pipeline.run([sf])[0].outcome for _ in range(4)]
    assert outcomes == ["failed", "failed", "quarantined", "skipped"]
    with session_scope(engine) as session:
        row = session.get_one(Document, sf.source_key)
        assert row.attempts == 3
        assert row.error == "ValueError: corrupt file"


def test_answer_cites_sources_and_shows_versions(
    pipeline: Pipeline, settings: Settings, client: QdrantClient, tmp_path: Path
) -> None:
    pipeline.run([source(tmp_path / "v1.txt", DATASHEET_V1, 1)])
    pipeline.run([source(tmp_path / "v2.txt", DATASHEET_V2, 2)])
    llm = ScriptedLLM("The current limit is 85 °C [S1]; v1 stated 90 °C [S2] [S9].")
    service = RagService(settings, FakeEmbedder(), OverlapReranker(), client, llm)

    result = service.answer("What is the maximum coolant outlet temperature of System B?")

    assert result.found
    assert result.cited == [1, 2]
    assert result.invalid_citations == [9]
    assert {s.doc_version for s in result.sources[:2]} == {1, 2}
    prompt = llm.messages[1]["content"]
    assert "(superseded)" in prompt and "(latest)" in prompt
    assert "Answer in English" in llm.messages[0]["content"]


def test_not_found_skips_the_llm(
    pipeline: Pipeline, settings: Settings, client: QdrantClient, tmp_path: Path
) -> None:
    pipeline.run([source(tmp_path / "v1.txt", DATASHEET_V1)])
    llm = ScriptedLLM("should not be called")
    service = RagService(settings, FakeEmbedder(), OverlapReranker(), client, llm)

    result = service.answer("Wie lange ist die Garantiezeit des Kunden?")

    assert not result.found
    assert result.language == "de"
    assert result.answer.startswith("Dazu habe ich")
    assert llm.messages == []


def test_system_filter(
    pipeline: Pipeline, settings: Settings, client: QdrantClient, tmp_path: Path
) -> None:
    pipeline.run([source(tmp_path / "v1.txt", DATASHEET_V1)])
    service = RagService(settings, FakeEmbedder(), OverlapReranker(), client, None)
    assert service.retrieve("coolant outlet temperature", Filters(systems=["System A"])) == []
    assert service.retrieve("coolant outlet temperature", Filters(systems=["System B"]))


def test_routing_detects_systems_and_parameters(repo_root: Path) -> None:
    from fcrag.ingest.extract_params import Vocabulary
    from fcrag.retrieval.route import detect

    vocab = Vocabulary.from_truth(
        repo_root / "data_gen/systems", repo_root / "data_gen/synonyms.yaml"
    )
    route = detect("Vergleiche die Membrandicke der Stacks von System A, B und C.", vocab)
    assert route.systems == ["System A", "System B", "System C"]
    assert route.keys == ["membrane_thickness"]
    route = detect("What is the maximum coolant outlet temperature of System B?", vocab)
    assert route.keys == ["coolant_outlet_temperature_max"] and route.is_parameter_query
    assert not detect("What causes membrane drying?", vocab).is_parameter_query


def test_parameter_questions_get_exact_records_first(
    pipeline: Pipeline, settings: Settings, client: QdrantClient, engine: Engine, tmp_path: Path,
    repo_root: Path,
) -> None:  # fmt: skip
    from fcrag.ingest.extract_params import Vocabulary
    from fcrag.retrieval.route import SqlParameterStore

    pipeline.run([source(tmp_path / "v1.txt", DATASHEET_V1, 1)])
    pipeline.run([source(tmp_path / "v2.txt", DATASHEET_V2, 2)])
    llm = ScriptedLLM("85 °C [S1]; v1 said 90 °C [S2].")
    vocab = Vocabulary.from_truth(
        repo_root / "data_gen/systems", repo_root / "data_gen/synonyms.yaml"
    )
    service = RagService(
        settings, FakeEmbedder(), OverlapReranker(), client, llm,
        params=SqlParameterStore(engine), vocabulary=vocab,
    )  # fmt: skip

    result = service.answer("What is the maximum coolant outlet temperature of System B?")

    first, second = result.sources[0], result.sources[1]
    assert (first.kind, first.doc_version, first.is_latest) == ("parameter", 2, True)
    assert "B-STK" in first.text and "85 °C" in first.text
    assert (second.kind, second.doc_version, second.is_latest) == ("parameter", 1, False)
    assert [s.label for s in result.sources] == [f"S{i}" for i in range(1, len(result.sources) + 1)]


def test_requirement_questions_are_detected() -> None:
    from fcrag.generation.answer import REQUIREMENT_WORDS

    assert REQUIREMENT_WORDS.search("Stimmt die Anforderung zum Druck mit der Liste überein?")
    assert REQUIREMENT_WORDS.search("Which requirements refine REQ-A-0001?")
    assert REQUIREMENT_WORDS.search("What is the parent of REQ-C-0031?")
    assert not REQUIREMENT_WORDS.search("What is the rated net power of System A?")
    assert not REQUIREMENT_WORDS.search("Is it required to purge?")  # no whole-word match


def test_eval_keeps_retrieval_metrics_when_the_llm_fails(
    pipeline: Pipeline, settings: Settings, client: QdrantClient, tmp_path: Path
) -> None:
    from collections.abc import Iterator as It

    from fcrag.eval.golden import GoldenItem
    from fcrag.eval.runner import evaluate_item, summarize

    class RateLimited:
        model = "fake/limited"

        def stream(self, messages: list[dict[str, str]]) -> It[str]:
            raise RuntimeError("rate limit")

    pipeline.run([source(tmp_path / "v1.txt", DATASHEET_V1)])
    service = RagService(settings, FakeEmbedder(), OverlapReranker(), client, RateLimited())
    item = GoldenItem(
        id="q", category="parameter", language="en", reference_answer="90 °C",
        question="What is the maximum coolant outlet temperature of System B?",
        gold_sources=[{"doc_id": "ds-stack-b"}],
    )  # fmt: skip
    result = evaluate_item(service, item, settings, answers=True)
    assert result.rank == 1 and result.answer is None and "rate limit" in (result.error or "")
    assert result.candidate_chars > 0 and sum(result.candidate_types.values()) >= 1
    summary = summarize([result])
    assert summary["recall@5"] == 1.0 and summary["errors"] == 1 and "answers" not in summary
