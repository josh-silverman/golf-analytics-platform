# PGA Tour Analytics Platform

> Production-grade ML platform for PGA Tour outcome prediction and betting edge
> analysis. Built end-to-end: data ingestion → strokes-gained feature engineering
> → gradient-boosted outcome classification → per-market calibration →
> model-vs-market divergence with Kelly-sized framing.

**Status:** Phase 0 — Foundation. The full 12-section system design is complete and committed under [`docs/architecture/`](docs/architecture/); the runtime so far is the FastAPI scaffold, the React dashboard skeleton, and a docker-compose dev stack. Phase 1+ adds the data layer, model, simulator, and betting edge analysis — see the [Roadmap](#roadmap) below.

## Highlights — planned

Sourced from the architecture docs. Items marked **(shipped)** work today.

- **Calibrated probabilistic predictions** for win, T5, T10, and make-cut. Skill-and-simulate architecture rather than one-model-per-outcome — see [02 §4](docs/architecture/02-technical-core.md).
- **Betting edge analysis** — model-vs-market divergence with fractional Kelly sizing across win, top-5, top-10, and top-20 markets.
- **Live model comparison vs. DataGolf** — head-to-head Brier scores on common events. The DataGolf benchmark page is the project's signature demo asset.
- **Pluggable data providers** (`DataProvider` interface, decorator-wrapped Redis cache, contract-tested) so mock and DataGolf implementations swap without touching consumers — see [02 §5](docs/architecture/02-technical-core.md).
- **Production-grade engineering** — release-time Alembic migrations, structured JSON logging with trace IDs, calibration drift monitoring, and an actual runbook. **(shipped)** scaffolds for these are in place.

## Quick start

```bash
docker compose up --build
```

That's the whole thing. After ~60s on first boot (image build + dep install) you get:

| URL                                       | What                              |
|-------------------------------------------|-----------------------------------|
| <http://localhost:5173>                   | React dashboard (Vite, HMR)       |
| <http://localhost:8000/api/v1/healthz>    | Liveness probe                    |
| <http://localhost:8000/api/v1/readyz>     | Readiness — DB + Redis status     |
| <http://localhost:8000/api/docs>          | OpenAPI / Swagger UI              |

The dashboard at `/` fetches `/api/v1/healthz` through the Vite dev-server proxy and renders the backend status, proving the full request path works.

`make help` lists the common dev tasks (`dev`, `test`, `lint`, `typecheck`, `format`, `clean`, plus backend/frontend variants).

## Architecture

The full topology is in [01 §2](docs/architecture/01-vision-and-system-design.md). The Phase 0 runtime slice:

```
┌─────────────────────────┐
│  Browser (React SPA)    │  Vite + React 19 + Tailwind + TanStack Query
└──────────┬──────────────┘
           │  HTTPS / JSON
           ▼
┌─────────────────────────┐
│  FastAPI Application    │  Pydantic settings · structlog · async SQLAlchemy
└────┬───────────┬────────┘
     ▼           ▼
┌──────────┐  ┌──────────┐
│ Postgres │  │  Redis   │  Migrations via Alembic, release-phase only (no
│   16     │  │   7      │  startup migrations — known antipattern, doc 03 §4)
└──────────┘  └──────────┘
```

Phase 1+ adds the Prefect ingestion + training pipelines, a `DataProvider` interface with `MockDataProvider` and `DataGolfProvider`, the model registry, and the betting edge layer. See the [planning docs](docs/architecture/) for the full picture.

## Project structure

```
.
├── backend/                 FastAPI + ML + pipelines (Python 3.12, uv)
│   ├── app/                   Application code (config, logging, api, db, cache)
│   ├── alembic/               Migrations (async env, settings-driven URL)
│   ├── tests/                 pytest + FastAPI dependency overrides
│   ├── pyproject.toml         deps and tool config (ruff, mypy, pytest)
│   ├── uv.lock                Locked deps
│   └── Dockerfile             Dev image (prod target lands Session 5/Phase 5)
├── frontend/                React 19 + TypeScript dashboard
│   ├── src/
│   │   ├── routes/              React Router 7 route components
│   │   ├── lib/api/             TanStack Query hooks
│   │   └── test/                Vitest setup
│   ├── tailwind.config.ts     Dark theme tokens from doc 03 §3
│   ├── vite.config.ts         Dev proxy /api → backend
│   └── Dockerfile             Dev image
├── pipelines/               Prefect flows (Phase 1+)
├── infra/                   Reserved for fly.toml, deploy scripts (Session 5+)
├── docs/
│   └── architecture/        The 12-section planning pass — read these first
├── docker-compose.yml       postgres · redis · api · frontend (healthchecked)
├── Makefile                 dev · test · lint · typecheck · format · clean
└── .github/workflows/ci.yml ruff · mypy · pytest · eslint · tsc · vitest · build · docker
```

## Tech stack

| Layer              | Choice                                  | Why                                                                 |
|--------------------|-----------------------------------------|---------------------------------------------------------------------|
| Backend framework  | FastAPI + Pydantic v2                   | Async-first, Pydantic models double as data contracts and OpenAPI   |
| Python tooling     | uv, ruff, mypy (strict), pytest         | One toolchain, locked deps, fast feedback                           |
| Database           | PostgreSQL 16                           | Materialized views + JSONB for feature storage                      |
| Cache / queue      | Redis 7                                 | Per-endpoint TTL cache                                               |
| Migrations         | Alembic (async, release-phase)          | DB url from Pydantic settings; no startup migrations                |
| Frontend framework | Vite 6 + React 19 + TS strict           | Vite for HMR speed, React 19 for current ecosystem                  |
| Routing / data     | React Router 7 · TanStack Query 5       | Server state stale-while-revalidate; Zustand for local UI state     |
| Styling            | Tailwind 3.4 with dark tokens           | Premium dark theme per doc 03 §3; tabular numerics for stats        |
| Frontend tooling   | eslint flat config, vitest 4, jsdom     | Fast, modern, zero-config typescript-eslint                         |
| Local dev          | docker compose (Colima-compatible)      | Whole stack boots with one command                                  |
| Deploy target      | Fly.io (api + worker) · Vercel (web)    | "Polished but practical" — $20–40/mo per doc 03 §4                  |
| CI                 | GitHub Actions, three jobs              | Backend / frontend / docker image — concurrency-cancelled per ref   |

ML stack (sklearn HistGradientBoosting with per-market calibration, MLflow-style registry) is shipped.

## Planning documents

The 12-section architecture pass that scoped this project lives in [`docs/architecture/`](docs/architecture/):

- [01 — Vision and system design](docs/architecture/01-vision-and-system-design.md) — product vision, layered architecture, the 10 major engineering tradeoffs, and the phased build plan
- [02 — Technical core](docs/architecture/02-technical-core.md) — database schema (with the as-of-date pattern for leakage prevention), pipeline DAG, feature engineering structure, simulation engine internals, the `DataProvider` interface, and the mock data calibration targets
- [03 — Integration and deployment](docs/architecture/03-integration-and-deployment.md) — DataGolf API mapping with rate-limit strategy, API contract, UI architecture, deployment topology ($20–40/mo target), CI/CD shape, observability, and the GitHub presentation strategy this README implements

## Roadmap

Phasing from [01 §4](docs/architecture/01-vision-and-system-design.md). Each phase ends with a demoable artifact.

- **Phase 0 — Foundation.** Monorepo, FastAPI `/healthz` + `/readyz`, React shell, docker-compose, CI. *Demo:* the whole stack boots. **← shipped**
- **Phase 1 — Data layer & mock provider.** `DataProvider` interface, `MockDataProvider` generating ~5 years of statistically plausible tour data, Postgres schema, ingestion pipeline, read-only player/tournament endpoints. *Demo:* browse players and tournaments.
- **Phase 2 — Feature engineering & first model.** SG features, gradient-boosted trees (sklearn HistGradientBoosting), model registry, per-market calibration (sigmoid for win/top-5, isotonic for top-10/20/cut), predictions endpoint, leaderboard view. *Demo:* model predicts this week's field. **← shipped**
- **Phase 4 — Betting edge & analytics polish.** Real DataGolf sportsbook odds, edge calculation, fractional Kelly sizing, calibration reliability page, custom SVG visualizations, player trend pages. *Demo:* model-vs-market divergence with Kelly-sized framing. **← shipped**
- **Phase 5 — Production polish & DataGolf integration.** Fly.io + Vercel deploy, Sentry + Axiom, `DataGolfProvider` swap (the contract-test suite validates it), the model-vs-DataGolf benchmark page, runbook, Loom walkthrough.

## License

MIT. See [LICENSE](LICENSE). DataGolf is acknowledged as the data source once the integration lands in Phase 5.
