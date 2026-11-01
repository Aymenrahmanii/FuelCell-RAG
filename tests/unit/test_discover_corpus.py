"""Corpus discovery: parses OSTI and arXiv responses, keeps only new fuel cell documents."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, get_args

import pytest
import yaml

from fcrag.models import DocType

ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2404.07508v2</id>
    <published>2024-04-11T10:00:00Z</published>
    <title>A 1D model of a PEM fuel cell
      with liquid water</title>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2501.00001v1</id>
    <published>2025-01-01T10:00:00Z</published>
    <title>Graph neural networks for weather</title>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2502.11111v3</id>
    <published>2025-02-01T10:00:00Z</published>
    <title>Degradation of PEMFC catalysts</title>
  </entry>
</feed>"""

OSTI_PAGE = [
    {"osti_id": "1234567", "title": "Fuel Cell  Bus Evaluation: Third Report",
     "publication_date": "2019-08-01T00:00:00Z", "language": "English",
     "research_orgs": ["National Renewable Energy Laboratory (NREL)"],
     "links": [{"rel": "fulltext", "href": "https://www.osti.gov/servlets/purl/1234567"}]},
    {"osti_id": "7654321", "title": "Battery thermal runaway", "language": "English"},
    {"osti_id": "1111111", "title": "Brennstoffzellen im Test", "language": "German"},
    {"osti_id": "2222222", "title": "Solid oxide fuel cell stacks", "language": "English",
     "publication_date": None, "links": []},
]  # fmt: skip


def load_script(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "discover_corpus", repo_root / "scripts" / "discover_corpus.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOE_PAGE = (
    '<a href="/docs/hydrogenprogramlibraries/pdfs/11003_fuel_cell_stack_durability.pdf?sfvrsn=1">'
    "Fuel Cell Stack  Durability</a>"
    '<a href="/docs/hydrogenprogramlibraries/pdfs/12014_current_us_hydrogen_production.pdf?x=2">'
    "Current U.S. Hydrogen Production</a>"
)


def fake_get(url: str) -> bytes:
    if "hydrogen.energy.gov" in url:
        return DOE_PAGE.encode()
    if url.startswith("https://www.osti.gov/"):
        return json.dumps(OSTI_PAGE if "page=1" in url else []).encode()
    if "start=0" in url:
        return ARXIV_FEED.encode()
    return b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def test_discovery_keeps_new_fuel_cell_documents(repo_root: Path) -> None:
    script = load_script(repo_root)
    existing = [{"id": "arxiv-2404.07508-1d-pem-model", "title": "Old title",
                 "url": "https://arxiv.org/pdf/2404.07508"}]  # fmt: skip
    found = script.discover(fake_get, existing, target=50, pages=2, pause_s=0)

    ids = [e["id"] for e in found]
    assert "osti-1234567" in ids and "osti-2222222" in ids
    assert "osti-7654321" not in ids  # not about fuel cells
    assert "osti-1111111" not in ids  # not English
    assert not any(i.startswith("arxiv-2404.07508") for i in ids)  # URL already in the corpus
    assert "arxiv-2502.11111-degradation-of-pemfc-catalysts" in ids
    assert not any("2501.00001" in i for i in ids)
    assert len(ids) == len(set(ids))  # each query returns the same records: no duplicates

    bus = next(e for e in found if e["id"] == "osti-1234567")
    assert bus["title"] == "Fuel Cell Bus Evaluation: Third Report" and bus["year"] == 2019
    assert bus["publisher"] == "National Renewable Energy Laboratory (NREL)"
    sofc = next(e for e in found if e["id"] == "osti-2222222")
    assert sofc["url"] == "https://www.osti.gov/servlets/purl/2222222" and "year" not in sofc
    pem = next(e for e in found if e["id"].startswith("arxiv-2502"))
    assert pem["url"] == "https://arxiv.org/pdf/2502.11111" and pem["format"] == "paper"


def test_target_limits_discovery(repo_root: Path) -> None:
    script = load_script(repo_root)
    assert len(script.discover(fake_get, [], target=2, pages=1, pause_s=0)) == 2


def test_discovered_manifest_is_valid_when_present(repo_root: Path) -> None:
    path = repo_root / "data" / "sources.discovered.yaml"
    if not path.exists():
        pytest.skip("no discovered manifest yet")
    entries: list[dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]
    main = yaml.safe_load((repo_root / "data" / "sources.yaml").read_text(encoding="utf-8"))
    ids = [e["id"] for e in entries] + [e["id"] for e in main["sources"]]
    assert len(ids) == len(set(ids))
    for e in entries:
        for field in ("id", "url", "title", "publisher", "licence", "doc_type", "format"):
            assert e.get(field), f"{e.get('id')}: missing {field}"
        assert e["url"].startswith("https://"), e["id"]
        assert e["doc_type"] in get_args(DocType), e["id"]


def test_ingestion_reads_titles_from_the_discovered_manifest(tmp_path: Path) -> None:
    from fcrag.ingest.discover import load_metadata

    entry = {"id": "osti-1", "url": "https://x", "title": "Bus report", "publisher": "NREL",
             "licence": "DOE", "doc_type": "report", "format": "report"}  # fmt: skip
    (tmp_path / "sources.yaml").write_text(
        yaml.safe_dump({"sources": [{**entry, "id": "doe-1", "title": "Record"}]}), "utf-8"
    )
    meta = load_metadata(tmp_path / "sources.yaml", [])
    assert set(meta) == {"doe-1.pdf"}
    (tmp_path / "sources.discovered.yaml").write_text(yaml.safe_dump({"sources": [entry]}), "utf-8")
    meta = load_metadata(tmp_path / "sources.yaml", [])
    assert meta["osti-1.pdf"]["title"] == "Bus report" and meta["doe-1.pdf"]["title"] == "Record"


def test_doe_records_keep_only_fuel_cell_titles(repo_root: Path) -> None:
    script = load_script(repo_root)
    found = script.discover(fake_get, [], target=50, pages=1, pause_s=0)
    doe = [e for e in found if e["id"].startswith("doe-record-")]
    assert [e["title"] for e in doe] == ["Fuel Cell Stack Durability"]
    assert doe[0]["url"].startswith("https://www.hydrogen.energy.gov/docs/")
    assert doe[0]["url"].endswith(".pdf?sfvrsn=1") is False and doe[0]["url"].endswith(".pdf")
