"""The corpus manifest is complete and the download script refuses bad files."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, get_args

import pytest
import yaml

from fcrag.models import DocType

FORMATS = {"record", "report", "presentation", "paper", "fact_sheet"}


def load_script(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "download_corpus", repo_root / "scripts" / "download_corpus.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sources(repo_root: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load((repo_root / "data" / "sources.yaml").read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = data["sources"]
    return entries


def test_manifest_entries_are_complete(sources: list[dict[str, Any]]) -> None:
    assert len(sources) >= 30
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids))
    for s in sources:
        for field in ("id", "url", "title", "publisher", "year", "licence", "doc_type", "format"):
            assert s.get(field), f"{s.get('id')}: missing {field}"
        assert s["url"].startswith("https://"), s["id"]
        assert s["doc_type"] in get_args(DocType), s["id"]
        assert s["format"] in FORMATS, s["id"]


def test_lock_covers_every_source(repo_root: Path, sources: list[dict[str, Any]]) -> None:
    lock = yaml.safe_load((repo_root / "data" / "sources.lock.yaml").read_text(encoding="utf-8"))
    assert {s["id"] for s in sources} == set(lock)


def _manifest(tmp_path: Path, source_file: Path) -> Path:
    manifest = tmp_path / "sources.yaml"
    entry = {
        "id": "doc",
        "url": source_file.as_uri(),
        "title": "t",
        "publisher": "p",
        "licence": "l",
        "doc_type": "report",
    }
    manifest.write_text(yaml.safe_dump({"sources": [entry]}), encoding="utf-8")
    return manifest


def test_download_records_then_verifies_checksum(repo_root: Path, tmp_path: Path) -> None:
    script = load_script(repo_root)
    upstream = tmp_path / "upstream.pdf"
    upstream.write_bytes(b"%PDF-1.7 first version")
    manifest = _manifest(tmp_path, upstream)
    out = tmp_path / "raw"

    assert script.sync(manifest, out) == 0
    assert (out / "doc.pdf").read_bytes() == upstream.read_bytes()
    assert "doc" in yaml.safe_load((tmp_path / "sources.lock.yaml").read_text(encoding="utf-8"))

    (out / "doc.pdf").write_bytes(b"%PDF-1.7 tampered")
    assert script.sync(manifest, out) == 1


def test_download_rejects_non_pdf(repo_root: Path, tmp_path: Path) -> None:
    script = load_script(repo_root)
    page = tmp_path / "blocked.html"
    page.write_bytes(b"<!DOCTYPE html><title>Access denied</title>")
    out = tmp_path / "raw"

    assert script.sync(_manifest(tmp_path, page), out) == 1
    assert not list(out.iterdir())
