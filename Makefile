.PHONY: install up down logs test lint fmt typecheck check corpus

install:
	uv sync
	uv run pre-commit install

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

test:
	uv run pytest --cov -m "not integration"

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

check: lint typecheck test

corpus:
	uv run python scripts/download_corpus.py
