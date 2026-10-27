"""Command line: ``fcrag db-upgrade | ingest | search | ask | serve``."""

import argparse
import logging
import os
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
    categories = list(args.category or [])
    if args.gate:
        from fcrag.eval.gate import gate_categories

        categories += gate_categories(Path(args.gate))
    if categories:
        items = [i for i in items if i.category in categories]
    if args.limit:
        items = items[: args.limit]
    summary, path = run(
        _service(), items, get_settings(), name=args.name, answers=args.answers,
        out_dir=Path("eval/runs"), pause_s=args.pause,
    )  # fmt: skip
    print(json.dumps(summary, indent=2))
    print(f"saved {path}")
    from fcrag.observability import flush

    flush()
    if args.gate:
        from fcrag.eval.gate import check_gate

        failures = check_gate(summary, Path(args.gate))
        for failure in failures:
            print(f"GATE FAILED: {failure}")
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::error title=eval gate::{failure}")
        if failures:
            sys.exit(1)
        print("gate passed")


def _eval_judge(args: argparse.Namespace) -> None:
    import json
    from pathlib import Path

    from fcrag.eval.judge import faithfulness, judge_run, litellm_judge, write_judgements

    get_settings()  # loads provider keys from .env
    path = Path(args.run)
    run = json.loads(path.read_text(encoding="utf-8"))
    judgements = judge_run(run, litellm_judge(args.model), pause_s=args.pause)
    out = path.with_suffix(".judgements.jsonl")
    write_judgements(judgements, out)
    summary = faithfulness(judgements) | {"judge_model": args.model}
    run["summary"].setdefault("answers", {})["faithfulness"] = summary["faithfulness"]
    run["summary"]["judge"] = summary
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"judgements: {out} (fill in 'human' for a sample, then run fcrag judge-agreement)")


def _judge_label(args: argparse.Namespace) -> None:
    import json
    from pathlib import Path

    from fcrag.eval.judge import agreement, label_interactively

    path = Path(args.judgements)
    run = json.loads(Path(args.run).read_text(encoding="utf-8"))
    done = label_interactively(path, run, sample=args.sample)
    print(f"\nlabelled {done} this session")
    print(json.dumps(agreement(path), indent=2))


def _judge_agreement(args: argparse.Namespace) -> None:
    import json
    from pathlib import Path

    from fcrag.eval.judge import agreement

    print(json.dumps(agreement(Path(args.judgements), args.field), indent=2))


def _eval_rescore(args: argparse.Namespace) -> None:
    import json
    from pathlib import Path

    from fcrag.eval.golden import read_golden
    from fcrag.eval.runner import rescore

    path = Path(args.run)
    run = rescore(json.loads(path.read_text(encoding="utf-8")),
                  read_golden(Path("eval/golden_set.jsonl")))  # fmt: skip
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(run["summary"].get("answers", {}), indent=2))


def _eval_report(args: argparse.Namespace) -> None:
    from pathlib import Path

    from fcrag.eval.report import load_runs, markdown

    runs = load_runs(Path("eval/runs"))
    if args.only:
        runs = [r for r in runs if any(name in r["name"] for name in args.only)]
    print(markdown(runs))


def _eval_params(args: argparse.Namespace) -> None:
    import json
    from pathlib import Path

    from fcrag.db.session import get_engine
    from fcrag.eval.parameters import evaluate_parameters

    print(json.dumps(evaluate_parameters(get_engine(), Path(args.facts)), indent=2))


def _ingest(args: argparse.Namespace) -> None:
    from fcrag.ingest.pipeline import ingest_all

    counts = ingest_all(get_settings(), force=args.force, only=args.only, limit=args.limit)
    print(f"done: {counts}")
    if counts.get("failed") or counts.get("quarantined"):
        sys.exit(1)


def _worker(_: argparse.Namespace) -> None:
    from fcrag.ingest.worker import run_worker

    run_worker()


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
    p.add_argument("--only", action="append", help="glob on doc_id, e.g. 'doe-rec-*'; repeatable")
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
    p.add_argument("--gate", help="thresholds file (eval/gate.yaml); exit 1 if violated")
    p.add_argument("--pause", type=float, default=0.0, help="seconds between answered questions")
    p.set_defaults(func=_eval)

    p = sub.add_parser("eval-judge", help="LLM-judge faithfulness of a saved run's answers")
    p.add_argument("run", help="eval/runs/<run>.json from fcrag eval --answers")
    p.add_argument("--model", default="groq/qwen/qwen3.8-27b",
                   help="judge model; use a different family from the generator")  # fmt: skip
    p.add_argument("--pause", type=float, default=2.0, help="seconds between judge calls")
    p.set_defaults(func=_eval_judge)

    p = sub.add_parser("judge-label", help="label judge decisions by hand (interactive)")
    p.add_argument("judgements", help="the .judgements.jsonl next to the run")
    p.add_argument("run", help="the run .json the judgements came from")
    p.add_argument("--sample", type=int, default=50)
    p.set_defaults(func=_judge_label)

    p = sub.add_parser("judge-agreement", help="judge vs human labels in a judgements file")
    p.add_argument("judgements")
    p.add_argument("--field", default="human", help="label field: human (default) or claude")
    p.set_defaults(func=_judge_agreement)

    p = sub.add_parser("eval-rescore", help="re-score a saved run's answers (no LLM calls)")
    p.add_argument("run")
    p.set_defaults(func=_eval_rescore)

    p = sub.add_parser("eval-report", help="print saved runs as a Markdown table")
    p.add_argument("--only", action="append", help="substring of run names to include")
    p.set_defaults(func=_eval_report)

    p = sub.add_parser("eval-params", help="score extracted parameters against generator facts")
    p.add_argument("--facts", default="data/generated/facts.jsonl")
    p.set_defaults(func=_eval_params)

    p = sub.add_parser("worker", help="run the background ingestion worker (Redis queue)")
    p.set_defaults(func=_worker)

    p = sub.add_parser("serve", help="run the API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=_serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
