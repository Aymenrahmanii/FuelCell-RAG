"""Cross-lingual retrieval: a German question is also searched with its English translation."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine

from fcrag.config import Settings
from fcrag.db.models import Base
from fcrag.generation.answer import RagService, load_prompt
from fcrag.generation.translate import translate_query
from fcrag.ingest import parsers
from fcrag.ingest.pipeline import Pipeline
from fcrag.llm.client import Message
from fcrag.retrieval.search import Filters
from tests.fakes import FakeEmbedder, LineParser, OverlapReranker, ScriptedLLM
from tests.unit.test_pipeline import DATASHEET_V1, source


@pytest.fixture(autouse=True)
def line_parser(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(parsers, "_REGISTRY", [LineParser()])
    yield


@pytest.fixture
def client() -> QdrantClient:
    return QdrantClient(":memory:")


@pytest.fixture
def pipeline(client: QdrantClient) -> Pipeline:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, qdrant_collection="test", chunk_min_tokens=1)
    return Pipeline(settings, FakeEmbedder(), client, engine)


GERMAN = "Wie hoch ist die maximale Kühlmitteltemperatur am Austritt von System B?"
ENGLISH = "What is the maximum coolant outlet temperature of System B?"


class FailingLLM:
    model = "fake/failing"

    def stream(self, messages: list[Message]) -> Iterator[str]:
        raise OSError("rate limited")
        yield ""


def service(client: QdrantClient, llm: object, *, cross_lingual: bool) -> RagService:
    settings = Settings(
        _env_file=None, qdrant_collection="test", chunk_min_tokens=1, cross_lingual=cross_lingual
    )
    return RagService(settings, FakeEmbedder(), OverlapReranker(), client, llm)  # type: ignore[arg-type]


def top_score(svc: RagService) -> float:
    return svc.rank(GERMAN, Filters())[0].rerank_score or 0.0


def test_translation_makes_a_german_question_find_english_text(
    pipeline: Pipeline, client: QdrantClient, tmp_path: Path
) -> None:
    pipeline.run([source(tmp_path / "v1.txt", DATASHEET_V1)])
    off = top_score(service(client, ScriptedLLM(ENGLISH), cross_lingual=False))
    on = top_score(service(client, ScriptedLLM(ENGLISH), cross_lingual=True))
    assert on > off


def test_failed_translation_falls_back_to_the_question(
    pipeline: Pipeline, client: QdrantClient, tmp_path: Path
) -> None:
    pipeline.run([source(tmp_path / "v1.txt", DATASHEET_V1)])
    base = top_score(service(client, None, cross_lingual=False))
    assert top_score(service(client, FailingLLM(), cross_lingual=True)) == base


def test_english_questions_are_not_translated(
    pipeline: Pipeline, client: QdrantClient, tmp_path: Path
) -> None:
    llm = ScriptedLLM("should not be called")
    svc = service(client, llm, cross_lingual=True)
    assert svc.english_query(ENGLISH) is None
    assert llm.messages == []


def test_translation_is_cached_per_question() -> None:
    llm = ScriptedLLM(ENGLISH)
    svc = RagService(
        Settings(_env_file=None, cross_lingual=True),
        FakeEmbedder(), OverlapReranker(), QdrantClient(":memory:"), llm,
    )  # fmt: skip
    assert svc.english_query(GERMAN) == ENGLISH
    llm.answer = "something else"
    assert svc.english_query(GERMAN) == ENGLISH


def test_unchanged_output_means_no_second_search() -> None:
    prompt = load_prompt("translate")
    assert translate_query(ScriptedLLM(ENGLISH), ENGLISH, prompt) is None
    assert translate_query(ScriptedLLM(ENGLISH), GERMAN, prompt) == ENGLISH


def test_translation_does_not_turn_an_unanswerable_question_into_an_answerable_one(
    pipeline: Pipeline, client: QdrantClient, tmp_path: Path
) -> None:
    pipeline.run([source(tmp_path / "v1.txt", DATASHEET_V1)])
    svc = service(client, ScriptedLLM(ENGLISH), cross_lingual=True)
    svc.settings.rerank_threshold = 0.3
    ranked = svc.rank(GERMAN, Filters())
    assert (ranked[0].rerank_score or 0) >= 0.3  # the translation finds a good match ...
    assert ranked[0].evidence_score < 0.3  # ... but the German question as asked does not
    assert svc.retrieve(GERMAN, Filters()) == []
