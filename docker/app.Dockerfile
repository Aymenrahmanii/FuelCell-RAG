# FuelCell-RAG application image. One image, three roles (api, worker, ui) chosen by command.
# The "ml" target carries torch (CPU build on Linux), Docling and FlagEmbedding;
# the "ui" target only needs Streamlit and the HTTP client.
FROM python:3.12.12-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 \
    HF_HOME=/models HF_HUB_DISABLE_SYMLINKS_WARNING=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 app && mkdir -p /models /app/data && chown app /models /app/data

FROM base AS ml
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project --extra ml
COPY src ./src
COPY prompts ./prompts
COPY data_gen ./data_gen
COPY alembic.ini ./
RUN uv sync --locked --no-dev --extra ml
ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8000
CMD ["fcrag", "serve", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS ui
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project --extra ui
COPY src ./src
RUN uv sync --locked --no-dev --extra ui
ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8501
CMD ["streamlit", "run", "src/fcrag/ui/chat.py", "--server.address=0.0.0.0", "--server.port=8501"]
