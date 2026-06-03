# backend

FastAPI service for the PGA Tour Analytics Platform. Phase 0 scope: `/healthz`, `/readyz`, Pydantic settings, structlog JSON output, Alembic.

## Local development

```bash
# from this directory
cp .env.example .env                          # if it doesn't exist yet
uv sync                                        # install + create .venv
uv run uvicorn app.main:app --reload --port 8000
```

`/healthz` is liveness (always 200). `/readyz` pings Postgres + Redis — it returns 503 if either is down, so without Docker running you'll get a `not_ready` response. That's expected.

## Tests, lint, type check

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

## Migrations

```bash
uv run alembic upgrade head                    # apply pending
uv run alembic revision --autogenerate -m msg  # create new
```

Schema design lands in Phase 1; for now Alembic is configured with an empty `target_metadata`.
