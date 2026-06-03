# PGA Tour Analytics Platform

> Production-grade ML platform for PGA Tour outcome prediction, Monte Carlo simulation, and betting edge analysis.

This is the Phase 0 scaffold. The architecture, design decisions, and phasing are documented in detail:

- [01 — Vision and system design](docs/architecture/01-vision-and-system-design.md)
- [02 — Technical core](docs/architecture/02-technical-core.md)
- [03 — Integration and deployment](docs/architecture/03-integration-and-deployment.md)

A full README per section 8 of doc 03 (highlights, architecture diagram, quick start, deep dives, tech stack) lands in a later session once the stack boots.

## Structure

```
backend/      FastAPI + ML + pipelines (Python)         — Session 2+
frontend/     Vite + React + TypeScript dashboard       — Session 3+
pipelines/    Prefect flows                              — Phase 1
infra/        Dockerfiles, Fly.io config, GitHub Actions — Session 4+
docs/         Architecture and design docs
```

## Stack (locked)

Backend: FastAPI, Pydantic, Alembic, structlog, uv. Frontend: Vite, React, TypeScript, Tailwind, React Router, TanStack Query. Data: PostgreSQL, Redis. Deploy target: Fly.io (backend) + Vercel (frontend).
