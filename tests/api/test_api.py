"""API contract tests with an in-process service built on fakes."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from qdrant_client import QdrantClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

import fcrag.api.app as api
import fcrag.db.session as db_session
from fcrag.config import Settings
from fcrag.db.models import Base
from fcrag.generation.answer import RagService
from fcrag.ingest import parsers
from fcrag.ingest.discover import sha256_file
from fcrag.ingest.pipeline import Pipeline
from fcrag.models import SourceFile
from tests.fakes import FakeEmbedder, LineParser, OverlapReranker, ScriptedLLM


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> Engine:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_session, "get_engine", lambda dsn=None: engine)
    monkeypatch.setattr(api, "get_engine", lambda dsn=None: engine)
    return engine


@pytest.fixture
def client(engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(parsers, "_REGISTRY", [LineParser()])
    settings = Settings(
        _env_file=None, qdrant_collection="t", chunk_min_tokens=1, rerank_threshold=0.3
    )
    qdrant = QdrantClient(":memory:")
    path = tmp_path / "ds.txt"
    path.write_text("# 3 Limits\nThe maximum coolant outlet temperature is 85 °C.\n", "utf-8")
    sf = SourceFile(
        path=path, sha256=sha256_file(path), mime_type="text/plain", doc_id="ds", title="DS B"
    )
    Pipeline(settings, FakeEmbedder(), qdrant, engine).run([sf])
    service = RagService(
        settings, FakeEmbedder(), OverlapReranker(), qdrant, ScriptedLLM("It is 85 °C [S1].")
    )
    api.app.dependency_overrides[api.get_service] = lambda: service
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


QUESTION = {"question": "What is the maximum coolant outlet temperature?"}


def test_ask_returns_cited_answer(client: TestClient) -> None:
    body = client.post("/ask", json=QUESTION).json()
    assert body["answer"] == "It is 85 °C [S1]."
    assert body["cited"] == [1]
    assert body["sources"][0]["title"] == "DS B"
    assert body["sources"][0]["location"] == "p. 2"


def test_stream_emits_sources_tokens_done(client: TestClient) -> None:
    with client.stream("POST", "/ask/stream", json=QUESTION) as response:
        events = [
            json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")
        ]
    types = [e["type"] for e in events]
    assert types[0] == "sources" and types[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "token") == "It is 85 °C [S1]."


def test_validation_and_documents(client: TestClient) -> None:
    assert client.post("/ask", json={"question": ""}).status_code == 422
    docs = client.get("/documents").json()
    assert docs[0]["doc_id"] == "ds" and docs[0]["status"] == "indexed"
    assert "path" not in docs[0]


def test_feedback_is_stored(client: TestClient) -> None:
    response = client.post(
        "/feedback", json={"question": "q", "answer": "a", "rating": 1, "comment": "good"}
    )
    assert response.status_code == 201
    assert (
        client.post("/feedback", json={"question": "q", "answer": "a", "rating": 5}).status_code
        == 422
    )


def test_api_key_is_enforced(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    secured = Settings(_env_file=None, api_key=SecretStr("s3cret"))
    monkeypatch.setattr(api, "get_settings", lambda: secured)
    assert client.post("/ask", json=QUESTION).status_code == 401
    assert client.post("/ask", json=QUESTION, headers={"X-API-Key": "s3cret"}).status_code == 200
