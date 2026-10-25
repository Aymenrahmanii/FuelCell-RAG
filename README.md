# FuelCell-RAG

Production-grade retrieval-augmented generation over fuel cell engineering documents: PDFs,
parameter sheets, requirement specs, drawings and STEP files. Every claim in an answer cites a
page, table cell, requirement ID or CAD part.

All data is public or synthetic. The corpus describes three **fictional** PEM fuel cell systems:

| System | Application | Rated net power |
|---|---|---|
| A | Passenger car | 80 kW |
| B | Heavy-duty truck | 2 × 150 kW |
| C | Stationary CHP | 100 kW |

Each system is defined once in [`data_gen/systems/`](data_gen/systems/). These YAML files are the
single source of truth: generators turn them into documents, and the evaluation harness uses them
to know the exact answer to every parameter question.

> Status: **week 1 scaffold**. Repository, local stack, CI, system truths and smoke questions are
> in place; ingestion, retrieval and the UI follow in later phases.

## Quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
uv sync                      # install dependencies into .venv
uv run pre-commit install    # lint, format, type and secret checks on commit
cp .env.example .env         # then replace every CHANGEME
docker compose up -d         # Qdrant, Postgres, Redis, MinIO, Langfuse
uv run pytest                # unit tests
```

| Service | URL |
|---|---|
| Qdrant dashboard | http://localhost:6333/dashboard |
| Langfuse | http://localhost:3000 |
| MinIO console | http://localhost:9001 |

`make check` runs lint, types and tests together (on Windows, run the `uv run` commands from the
Makefile directly if `make` is not installed).

## Repository layout

```
src/fcrag/        package: config, shared schemas, ingest/, retrieval/, generation/, llm/, api/, ui/, db/
data_gen/systems/ YAML truth per fictional system
data/sources.yaml manifest of public documents (licence per entry); PDFs are never committed
eval/             smoke and golden question sets, metrics, run results
prompts/          versioned prompt files
tests/            unit/, parsers/ (golden files), api/, load/
docs/decisions/   architecture decision records
```

## Corpus

[`data/sources.yaml`](data/sources.yaml) lists 33 public documents with their licence:
- DOE Hydrogen Program records and plans
- Annual Merit Review presentations on cost, durability, heavy-duty trucks and air management
- NREL field-data reports
- open-access papers on modelling, degradation and stationary CHP

Fetch them with `uv run python scripts/download_corpus.py` into `data/raw/` (git-ignored). The
script rejects anything that is not a PDF and verifies every file against
[`data/sources.lock.yaml`](data/sources.lock.yaml), so a silently changed upstream document is
caught. No confidential or proprietary material is ever added.

## Evaluation

[`eval/smoke_questions.jsonl`](eval/smoke_questions.jsonl) holds 20 smoke questions (7 in German)
covering parameter lookups, cross-system comparisons, version conflicts, background facts and
unanswerable questions. Parameter answers reference the YAML truth, and a unit test keeps the two
in sync. The 60-question golden set and ablation table come in the evaluation phase.

## Licence

Code: MIT. Third-party documents keep their own licences and are not redistributed.
