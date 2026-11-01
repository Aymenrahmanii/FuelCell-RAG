"""Find public fuel cell documents and write them as a reviewable manifest.

Queries two public APIs and writes candidates in the format of data/sources.yaml to
data/sources.discovered.yaml (by default). Nothing is downloaded: review the file, then fetch it
with the existing downloader, which rejects anything that is not a PDF and locks checksums:

    uv run python scripts/discover_corpus.py --target 230
    uv run python scripts/download_corpus.py --manifest data/sources.discovered.yaml

Sources:
- OSTI.gov (US DOE Office of Scientific and Technical Information): DOE-funded technical reports
  with full text hosted by OSTI.
- arXiv: preprints, taken for research use under each author's arXiv licence.
- DOE Hydrogen Program records (hydrogen.energy.gov): short US government documents with direct PDF
  links; used when OSTI is unreachable from the current network.

Only documents whose title names fuel cells are kept, and ids or URLs already in
data/sources.yaml are skipped. The PDFs are never committed.
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from html import unescape
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "fcrag-corpus/0.1 (research corpus; one request at a time)"

OSTI_API = "https://www.osti.gov/api/v1/records"
OSTI_QUERIES = {
    "PEM fuel cell durability": ["durability"],
    "fuel cell system cost analysis": ["cost"],
    "fuel cell electric bus evaluation": ["bus", "fleet"],
    "fuel cell electric vehicle": ["automotive"],
    "fuel cell membrane electrode assembly": ["mea", "materials"],
    "fuel cell catalyst platinum": ["catalyst", "materials"],
    "fuel cell heavy duty truck": ["heavy-duty"],
    "stationary fuel cell combined heat and power": ["stationary", "chp"],
    "fuel cell air compressor balance of plant": ["balance-of-plant"],
    "fuel cell water thermal management": ["thermal", "water"],
    "solid oxide fuel cell": ["sofc"],
    "fuel cell hydrogen contaminants": ["contaminants"],
}
ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_QUERIES = {
    'ti:"PEM fuel cell"': ["pem"],
    'ti:"proton exchange membrane fuel cell"': ["pem"],
    'ti:"fuel cell" AND abs:degradation': ["durability"],
    'ti:"fuel cell" AND abs:"hydrogen vehicle"': ["automotive"],
    'ti:"solid oxide fuel cell"': ["sofc"],
}
DOE_BASE = "https://www.hydrogen.energy.gov"
DOE_RECORDS = f"{DOE_BASE}/library/program-records"
DOE_LINK = re.compile(
    r'<a href="(/docs/hydrogenprogramlibraries/pdfs/([^"/?]+)\.pdf)[^"]*">([^<]+)</a>'
)
ATOM = {"a": "http://www.w3.org/2005/Atom"}
FUEL_CELL = re.compile(r"fuel[\s-]*cells?|PEMFC|SOFC|Brennstoffzelle", re.IGNORECASE)

Fetch = Callable[[str], bytes]


def fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data: bytes = response.read()
    return data


def slug(text: str, words: int = 6) -> str:
    parts = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(parts[:words])


def _year(value: Any) -> int | None:
    match = re.match(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def osti_entries(
    get: Fetch, query: str, topics: list[str], pages: int, pause_s: float
) -> Iterator[dict[str, Any]]:
    """DOE technical reports with OSTI-hosted full text matching ``query``."""
    for page in range(1, pages + 1):
        params = {"q": query, "has_fulltext": "true", "product_type": "Technical Report",
                  "rows": 100, "page": page}  # fmt: skip
        records = json.loads(get(f"{OSTI_API}?{urllib.parse.urlencode(params)}") or b"[]")
        if not records:
            return
        for rec in records:
            osti_id, title = rec.get("osti_id"), " ".join(str(rec.get("title", "")).split())
            if not osti_id or not FUEL_CELL.search(title):
                continue
            if str(rec.get("language", "English")).lower() not in {"english", "en"}:
                continue
            links = {link.get("rel"): link.get("href") for link in rec.get("links", [])}
            orgs = rec.get("research_orgs") or rec.get("sponsor_orgs") or ["US DOE"]
            yield {
                "id": f"osti-{osti_id}",
                "url": links.get("fulltext") or f"https://www.osti.gov/servlets/purl/{osti_id}",
                "title": title,
                "publisher": "; ".join(orgs[:2]) if isinstance(orgs, list) else str(orgs),
                "year": _year(rec.get("publication_date")),
                "licence": "DOE-funded report via OSTI; research use, not redistributed",
                "doc_type": "report",
                "format": "report",
                "topics": topics,
            }
        time.sleep(pause_s)


def doe_entries(
    get: Fetch, query: str, topics: list[str], pages: int, pause_s: float
) -> Iterator[dict[str, Any]]:
    """DOE Hydrogen Program records about fuel cells; ``query`` is the page URL."""
    html = get(query).decode("utf-8", errors="replace")
    for path, name, raw_title in DOE_LINK.findall(html):
        title = " ".join(unescape(raw_title).split())
        if not FUEL_CELL.search(title):
            continue
        yield {
            "id": f"doe-record-{slug(name, 8)}",
            "url": f"{DOE_BASE}{path}",
            "title": title,
            "publisher": "US DOE Hydrogen and Fuel Cell Technologies Office",
            "year": None,
            "licence": "US government work; public domain",
            "doc_type": "report",
            "format": "report",
            "topics": topics,
        }
    time.sleep(pause_s)


def arxiv_entries(
    get: Fetch, query: str, topics: list[str], pages: int, pause_s: float
) -> Iterator[dict[str, Any]]:
    """arXiv preprints matching ``query`` (arXiv asks for 3 s between requests)."""
    for page in range(pages):
        params = {"search_query": query, "start": page * 100, "max_results": 100}
        root = ET.fromstring(get(f"{ARXIV_API}?{urllib.parse.urlencode(params)}"))
        entries = root.findall("a:entry", ATOM)
        if not entries:
            return
        for entry in entries:
            title = " ".join((entry.findtext("a:title", "", ATOM) or "").split())
            abs_url = entry.findtext("a:id", "", ATOM) or ""
            arxiv_id = re.sub(r"v\d+$", "", abs_url.rsplit("/abs/", 1)[-1])
            if not arxiv_id or not FUEL_CELL.search(title):
                continue
            yield {
                "id": f"arxiv-{arxiv_id.replace('/', '-')}-{slug(title, 4)}",
                "url": f"https://arxiv.org/pdf/{arxiv_id}",
                "title": title,
                "publisher": "arXiv",
                "year": _year(entry.findtext("a:published", "", ATOM)),
                "licence": "arXiv preprint, author's licence; research use, not redistributed",
                "doc_type": "report",
                "format": "paper",
                "topics": topics,
            }
        time.sleep(pause_s)


def discover(
    get: Fetch, existing: list[dict[str, Any]], target: int, pages: int = 2, pause_s: float = 3.0
) -> list[dict[str, Any]]:
    """Up to ``target`` new entries, alternating sources so neither dominates."""
    seen_ids = {e["id"] for e in existing}
    seen_urls = {e["url"] for e in existing}
    seen_titles = {e["title"].lower() for e in existing}
    streams = [osti_entries(get, q, t, pages, pause_s) for q, t in OSTI_QUERIES.items()]
    streams += [doe_entries(get, DOE_RECORDS, ["program-records"], pages, pause_s)]
    streams += [arxiv_entries(get, q, t, pages, pause_s) for q, t in ARXIV_QUERIES.items()]
    found: list[dict[str, Any]] = []
    while streams and len(found) < target:
        for stream in list(streams):
            try:
                entry = next(stream)
            except StopIteration:
                streams.remove(stream)
                continue
            except OSError as exc:  # one unreachable API must not stop the other
                print(f"WARN query failed: {exc}", file=sys.stderr)
                streams.remove(stream)
                continue
            key = entry["title"].lower()
            if entry["id"] in seen_ids or entry["url"] in seen_urls or key in seen_titles:
                continue
            if not entry["year"]:
                entry.pop("year")
            seen_ids.add(entry["id"])
            seen_urls.add(entry["url"])
            seen_titles.add(key)
            found.append(entry)
            if len(found) >= target:
                break
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=230, help="new documents to find")
    parser.add_argument("--existing", type=Path, default=REPO_ROOT / "data" / "sources.yaml")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "data" / "sources.discovered.yaml")  # fmt: skip
    parser.add_argument("--pages", type=int, default=2, help="result pages per query")
    args = parser.parse_args()

    existing = yaml.safe_load(args.existing.read_text(encoding="utf-8"))["sources"]
    if args.out.exists():  # keep earlier discoveries (and their reviewed edits) stable
        existing = existing + (yaml.safe_load(args.out.read_text(encoding="utf-8")) or {}).get(
            "sources", []
        )
    found = discover(fetch, existing, args.target, pages=args.pages)
    previous = (
        (yaml.safe_load(args.out.read_text(encoding="utf-8")) or {}).get("sources", [])
        if args.out.exists() else []
    )  # fmt: skip
    header = (
        "# Candidates from scripts/discover_corpus.py. Review before downloading: remove anything\n"
        "# off-topic or with an unsuitable licence. Fetch with\n"
        "#   uv run python scripts/download_corpus.py --manifest data/sources.discovered.yaml\n"
    )
    body = yaml.safe_dump({"sources": previous + found}, sort_keys=False, allow_unicode=True)
    args.out.write_text(header + body, encoding="utf-8")
    by_source = {"osti": 0, "arxiv": 0, "doe": 0}
    for entry in found:
        by_source[entry["id"].split("-", 1)[0]] += 1
    print(f"{len(found)} new candidates ({by_source['osti']} OSTI, {by_source['arxiv']} arXiv, "
          f"{by_source['doe']} DOE); "
          f"{len(previous) + len(found)} in {args.out}")  # fmt: skip


if __name__ == "__main__":
    main()
