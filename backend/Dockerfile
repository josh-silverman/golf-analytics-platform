# Dev image: same image runs in docker compose with the source bind-mounted
# at /app. A separate prod target lands in Session 5 alongside Fly.io config.
FROM python:3.12-slim AS dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# uv binary from the official thin image
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

# Install deps first so the layer is cached when only source changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# Source bind-mounted at runtime via docker compose; this COPY makes the
# image usable on its own (e.g. for CI image-build verification)
COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
