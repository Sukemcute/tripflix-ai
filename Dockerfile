# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.13-slim AS base
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

FROM dependencies AS dev
COPY . .
EXPOSE 8000
CMD [".venv/bin/fastapi", "dev", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS prod
ENV UV_NO_DEV=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev
COPY app ./app
USER 10001:10001
EXPOSE 8000
CMD [".venv/bin/fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
