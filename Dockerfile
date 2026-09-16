# Backend image for Railway: the live Brain HTTP bridge (Starlette + uvicorn) over
# Postgres/pgvector, with local fastembed (ONNX) embeddings. Built with uv from the lockfile.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv, pinned via the official distroless image
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer), then the project source.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Railway injects $PORT; the server binds 0.0.0.0 when it sees it (see http_server.main).
CMD ["uv", "run", "--no-sync", "digital-brain-http"]
