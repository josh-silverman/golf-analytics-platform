# ---------------------------------------------------------------------------
# Base: shared uv + system deps
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# uv binary from the official thin image
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

# ---------------------------------------------------------------------------
# Dev: mounts source at runtime via docker compose, hot-reload enabled
# ---------------------------------------------------------------------------
FROM base AS dev

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# Source bind-mounted at runtime via docker compose; this COPY makes the
# image usable on its own (e.g. for CI image-build verification)
COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------------------------------------------------------------------------
# Prod: no dev dependencies, no source-volume mount, non-root user
# ---------------------------------------------------------------------------
FROM base AS prod

# Install only production deps (no dev group)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-group dev

COPY . .

# Create a non-root user — Fly.io security best practice
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --gid 1001 appuser && \
    chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000

# Exec uvicorn straight from the baked venv. `uv run` would re-resolve the
# project at startup and needs a writable cache dir — the system user's home
# is /nonexistent, so uv crashes (exit 2) before uvicorn ever starts.
# workers = 2× vCPUs + 1 per Fly.io recommendation for I/O-heavy FastAPI apps
CMD ["/app/.venv/bin/uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info"]
