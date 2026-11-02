# Contributing

Small, focused pull requests to `main`, merged with a merge commit. Commit messages explain why
the change is made.

```
uv sync --extra ml --extra ui --extra cad
uv run ruff check src tests scripts ; uv run ruff format src tests scripts
uv run --extra ui mypy
uv run --extra ui pytest -m "not integration"
```

Ruff, ruff format, strict mypy and the tests must pass. CI also scans for secrets, audits the
locked dependencies and runs the retrieval evaluation gate (`eval/gate.yaml`).

- Prompts are versioned (`prompts/*.yaml`): bump `version:` on any change.
- The golden set is generated (`fcrag golden`); a test fails if it drifts.
- Public PDFs are never committed. Add sources to `data/sources.yaml` with their licence.
- Add a test with every new citation variant in `generation/citations.py`.
- Design decisions live in `docs/decisions/`; add an ADR for a change of architecture.
