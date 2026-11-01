# FuelCell-RAG: notes for Claude

Bilingual (German/English) RAG over fuel cell engineering documents with cited answers. Read
`README.md` for the system and its results, `docs/STATUS.md` for where the 12-week plan stands
and what is next, and `docs/decisions/` for why things are built the way they are.

## Commands

Python 3.12 with uv. The developer works on Windows (PowerShell: chain with `;`, not `&&`).

```
uv sync --extra ml --extra ui --extra cad   # all extras; `uv sync --extra ui` alone REMOVES torch etc.
docker compose up -d                        # Qdrant, Postgres, Redis, MinIO, Langfuse
uv run fcrag db-upgrade                     # Alembic migrations (latest 0004_audit_log)
uv run fcrag generate                       # synthetic corpus -> data/generated
uv run fcrag ingest                         # new or changed files only; --force to re-index
uv run fcrag serve --port 8001              # API on the GPU (the Docker API on :8000 is CPU-only)

uv run ruff check src tests scripts ; uv run ruff format src tests scripts
uv run --extra ui mypy                      # strict; needs the ui extra for streamlit stubs
uv run --extra ui pytest -m "not integration"
```

Evaluation (answers use the Groq free tier: 8,000 tokens/min, so pause between questions):

```
uv run fcrag eval --name <name> --answers --pause 8     # full golden set, saves eval/runs/<stamp>-<name>.json
uv run fcrag eval --answers --category injection        # one category
uv run fcrag eval-judge eval/runs/<run>.json            # faithfulness, writes <run>.judgements.jsonl
uv run fcrag eval-rescore eval/runs/<run>.json          # re-score a saved run, no LLM calls
uv run fcrag judge-agreement <run>.judgements.jsonl --field claude
```

## Conventions

- Small, focused PRs to `main`, merged with a merge commit (not squash). Commit messages explain
  why. Check: ruff, ruff format, mypy strict and tests pass before pushing.
- CI: `ci.yml` (lint, types, tests, pip-audit) and `eval.yml` (retrieval gate, 40 questions,
  30-50 min on CPU; thresholds in `eval/gate.yaml`). The gate reranks 20 candidates at 512 tokens
  (`FCRAG_PREFETCH_LIMIT`, `FCRAG_RERANK_MAX_LENGTH`); production uses 50 and 1024.
- `uv.lock` cannot be regenerated without the PyTorch index; do not add dependencies casually.
  Known, accepted pip-audit findings are listed with reasons in `.github/pip-audit-ignore.txt`.
- Prompts are versioned (`prompts/*.yaml`, `version:`); bump the version on any change. The
  response cache key includes it.
- Golden set: `eval/golden_set.jsonl` is generated from the system truths (`fcrag golden`); a
  test fails if it drifts. Gold sources are exact, recorded by the generators.
- Public PDFs are never committed: `data/sources.yaml` (curated, 33) and
  `data/sources.discovered.yaml` (from `scripts/discover_corpus.py`) list them with licences;
  `scripts/download_corpus.py --manifest ...` fetches them and locks checksums.
- `eval/runs/` is git-ignored. Runs that need sharing go to the `judge-labels` branch
  (`git add -f`); that branch also holds the second-opinion labels.

## Measuring faithfulness honestly

Faithfulness is judged claim by claim: every fact in a cited sentence must be in the sources
that sentence cites. The judge (`qwen/qwen3.8-27b`, judge-v2) is checked against blind
second-opinion labels in the `claude` field of the judgements file. Label without looking at
`supported`/`reason`, report both figures and the agreement rate, and never present LLM labels
as human labels. `write_judgements` keeps labels on re-judging and backs the file up if any
label would be dropped.

## Pitfalls already hit

- Answers stream (SSE): Locust's own `/ask/stream` row only times the headers; the locustfile
  records "time to first token" and "full answer" itself.
- Planted prompt-injection notes rank below the real documents, so the eval also answers with
  the note forced in as source 1 (`forced_resisted`).
- Citation variants the model writes (`【S1】`, `(vgl. S2)`, `[S1, S5]`) are normalised in
  `generation/citations.py`; add new variants there with a test.
- GitHub retargets stacked PRs only when the merged branch is deleted; prefer independent PRs.
