"""Command line: ``fcrag db-upgrade | ingest | search | ask | serve``."""

import argparse
import fnmatch
import logging
import sys
from typing import TYPE_CHECKING

from fcrag.config import get_settings

if TYPE_CHECKING:
    from fcrag.generation.answer import RagService


def _db_upgrade(_: argparse.Namespace) -> None:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")


def _generate(args: argparse.Namespace) -> None:
    from pathlib import Path

    from fcrag.datagen.run import generate

    files = generate(Path(args.systems), Path(args.out))
    facts = sum(len(f.facts) for f in files)
    print(f"generated {len(files)} files with {facts} facts in {args.out}")


def _golden(args: argparse.Namespace) -> None:
    from pathlib import Path

    from fcrag.eval.golden import build_golden, write_golden

    items = build_golden(Path("data_gen/systems"), Path("eval/golden_public.yaml"))
    write_golden(items, Path(args.out))
    counts: dict[str, int] = {}
    for item in items:
        counts[item.category] = counts.get(item.category, 0) + 1
    german = sum(i.language == "de" for i in items)
    print(f"{len(items)} questions ({german} German) -> {args.out}: {counts}")


def _eval(args: argparse.Namespace) -> None:
    import json
    from pathlib import Path

    from fcrag.eval.golden import read_golden
    from fcrag.eval.runner import run

    items = read_golden(Path(args.golden))
    if args.category:
        items = [i for i in items if i.category in args.category]
    if args.limit:
        items = items[: args.limit]
    summary, path = run(
        _service(), items, get_settings(), name=args.name, answers=args.answers,
        out_dir=Path("eval/runs"),
    )  # fmt: skip
    print(json.dumps(summary, indent=2))
    print(f"saved {path}")


def _ingest(args: argparse.Namespace) -> None:
    from fcrag.db.session import get_engine
    from fcrag.embedding import get_embedder
    from fcrag.ingest.discover import discover
    from fcrag.ingest.index import get_client
    from fcrag.ingest.pipeline import Pipeline

    s = get_settings()
    files = discover(s.source_dirs, s.sources_manifest)
    if args.only:
        files = [f for f in files if fnmatch.fnmatch(f.doc_id, args.only)]
    if args.limit:
        files = files[: args.limit]
    from fcrag.ingest.cache import ElementCache

    cache = ElementCache(s.element_cache_dir) if s.element_cache_dir else None
    pipeline = Pipeline(s, get_embedder(), get_client(), get_engine(), cache)
    results = pipeline.run(files, force=args.force)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome] = counts.get(r.outcome, 0) + 1
    chunks = sum(r.chunks for r in results)
    print(f"done: {counts}, {chunks} chunks indexed this run")
    if counts.get("failed") or counts.get("quarantined"):
        sys.exit(1)


def _service() -> "RagService":
    from fcrag.embedding import get_embedder
    from fcrag.generation.answer import RagService
    from fcrag.ingest.index import get_client
    from fcrag.llm.client import LiteLLMClient
    from fcrag.retrieval.rerank import get_reranker

    s = get_settings()
    from fcrag.db.session import get_engine
    from fcrag.ingest.extract_params import Vocabulary
    from fcrag.retrieval.route import SqlParameterStore

    return RagService(
        s, get_embedder(), get_reranker(), get_client(), LiteLLMClient(s),
        params=SqlParameterStore(get_engine()),
        vocabulary=Vocabulary.from_truth(s.systems_dir, s.synonyms_path),
    )  # fmt: skip


def _search(args: argparse.Namespace) -> None:
    from fcrag.retrieval.search import Filters

    sources = _service().retrieve(args.query, Filters(systems=args.system or []))
    if not sources:
        print("no source passed the rerank threshold")
    for src in sources:
        print(f"[{src.label}] {src.score:.3f}  {src.title} v{src.doc_version}  {src.location}")
        print("     " + src.text[:240].replace("\n", " ") + "\n")


def _ask(args: argparse.Namespace) -> None:
    from fcrag.retrieval.search import Filters

    for event in _service().stream(args.question, Filters(systems=args.system or [])):
        if event["type"] == "token":
            print(event["text"], end="", flush=True)
        elif event["type"] == "done":
            result = event["result"]
            print("\n")
            for src in result["sources"]:
                print(f"[{src['label']}] {src['title']} v{src['doc_version']}, {src['location']}")
            if result["invalid_citations"]:
                print(f"warning: invalid citations {result['invalid_citations']}")


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("fcrag.api.app:app", host=args.host, port=args.port)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    for noisy in ("httpx", "docling", "FlagEmbedding", "transformers", "RapidOCR"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(prog="fcrag")
    sub = parser.add_subparsers(required=True)

    sub.add_parser("db-upgrade", help="apply database migrations").set_defaults(func=_db_upgrade)

    p = sub.add_parser("generate", help="build the synthetic corpus from the system truths")
    p.add_argument("--systems", default="data_gen/systems")
    p.add_argument("--out", default="data/generated")
    p.set_defaults(func=_generate)

    p = sub.add_parser("ingest", help="parse and index new or changed files")
    p.add_argument("--force", action="store_true", help="re-index even unchanged files")
    p.add_argument("--only", help="glob on doc_id, e.g. 'doe-rec-*'")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=_ingest)

    for name, func, arg in (("search", _search, "query"), ("ask", _ask, "question")):
        p = sub.add_parser(name)
        p.add_argument(arg)
        p.add_argument("--system", action="append", help="filter by system, repeatable")
        p.set_defaults(func=func)

    p = sub.add_parser("golden", help="rebuild the golden question set from the truths")
    p.add_argument("--out", default="eval/golden_set.jsonl")
    p.set_defaults(func=_golden)

    p = sub.add_parser("eval", help="run the golden set and save metrics to eval/runs")
    p.add_argument("--name", default="run")
    p.add_argument("--golden", default="eval/golden_set.jsonl")
    p.add_argument("--answers", action="store_true", help="also generate answers (needs an LLM)")
    p.add_argument("--category", action="append")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=_eval)

    p = sub.add_parser("serve", help="run the API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=_serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
