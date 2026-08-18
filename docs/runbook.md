# PGA Analytics Platform — Runbook

Operational reference for deploying, configuring, and troubleshooting the
platform. Read this top-to-bottom on first setup; use the section headings
for quick reference thereafter.

---

## 1. Quick-start checklist

| Step | Command / action |
|------|-----------------|
| 1 | Buy DataGolf API key at [datagolf.com/api-access](https://datagolf.com/api-access) |
| 2 | Deploy backend → Fly.io (§ 3) |
| 3 | Deploy frontend → Vercel (§ 4) |
| 4 | Set secrets (§ 2) |
| 5 | Run bootstrap pipeline (§ 5) |
| 6 | Visit `/benchmark` to confirm live data is flowing |

---

## 2. Environment variables / secrets

### Backend (Fly.io secrets)

```bash
fly secrets set \
  DATABASE_URL="postgresql+asyncpg://..." \
  DATAGOLF_API_KEY="<your-key>" \
  DATA_PROVIDER="datagolf" \
  SENTRY_DSN="https://..." \     # optional
  SECRET_KEY="<random-64-chars>"  # if you add auth later
```

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | ✅ | — | Async Postgres URL (`postgresql+asyncpg://...`) |
| `DATAGOLF_API_KEY` | ✅ when `DATA_PROVIDER=datagolf` | — | DataGolf subscription key |
| `DATA_PROVIDER` | — | `mock` | `mock` or `datagolf` |
| `DATA_PROVIDER_CACHE` | — | `true` | Enable Redis response caching |
| `REDIS_URL` | — | `redis://localhost:6379/0` | Redis connection string |
| `SENTRY_DSN` | — | — | Sentry error tracking DSN |
| `SENTRY_TRACES_SAMPLE_RATE` | — | `0.1` | Fraction of requests traced |
| `ACTIVE_MODEL_NAME` | — | `golf_v1` | Which model version to serve |
| `MODEL_REGISTRY_PATH` | — | `./models` | Filesystem path to model artifacts |
| `ENVIRONMENT` | — | `development` | `development` \| `staging` \| `production` |
| `LOG_FORMAT` | — | `json` | `json` (prod) or `console` (dev) |

### Frontend (Vercel environment variables)

| Variable | Required | Purpose |
|----------|----------|---------|
| `VITE_SENTRY_DSN` | — | Sentry DSN for frontend error tracking |

> The frontend talks to the backend through Vercel's API proxy rewrite
> (`/api/*` → `https://pga-analytics-api.fly.dev/api/*`), so no backend URL
> env var is needed at build time.

---

## 3. Backend deployment (Fly.io)

### First deploy

```bash
cd backend

# Create the app (one-time)
fly launch --no-deploy --name pga-analytics-api

# Provision a Postgres database (one-time)
fly postgres create --name pga-analytics-db
fly postgres attach pga-analytics-db  # sets DATABASE_URL secret automatically

# Set remaining secrets
fly secrets set DATAGOLF_API_KEY=<your-key> DATA_PROVIDER=datagolf

# Deploy
fly deploy --dockerfile Dockerfile --build-target prod
```

### Subsequent deploys

```bash
fly deploy --dockerfile Dockerfile --build-target prod
```

### Run database migrations

Migrations run as a release command (Fly executes it before traffic shifts):

```toml
# fly.toml — already configured:
[deploy]
  release_command = "alembic upgrade head"
```

To run manually:

```bash
fly ssh console -C "alembic upgrade head"
```

### Scale

```bash
# Default: 1 shared-CPU-1x 512MB machine, auto-stop when idle
fly scale vm shared-cpu-1x --memory 512

# For high-traffic / no cold starts:
fly scale count 2
fly scale vm shared-cpu-2x --memory 1024
```

---

## 4. Frontend deployment (Vercel)

### First deploy

```bash
cd frontend
npx vercel --prod
```

Vercel auto-detects Vite. The `vercel.json` at the repo root configures:
- API proxy: `/api/*` → `https://pga-analytics-api.fly.dev/api/*`
- SPA rewrite: all unknown paths → `/index.html`
- Asset caching: `max-age=31536000, immutable` for hashed assets

### Environment variables (Vercel dashboard)

Add in **Project → Settings → Environment Variables**:

| Name | Value |
|------|-------|
| `VITE_SENTRY_DSN` | `https://...@sentry.io/...` (optional) |

### Subsequent deploys

Push to `main` — Vercel auto-deploys on every push.

---

## 5. Bootstrap (first-time data + model)

After deploying both services and setting all secrets, run the bootstrap
pipeline to verify the DataGolf connection and train the first model:

```bash
# Local (against Fly.io Postgres via fly proxy or local .env)
cd backend
export DATA_PROVIDER=datagolf
export DATAGOLF_API_KEY=<your-key>
uv run python -m app.cli.bootstrap

# On Fly.io directly
fly ssh console -C "python -m app.cli.bootstrap"
```

Expected output:

```
══════════════════════════════════════════════════════════════
PGA Analytics — Bootstrap
══════════════════════════════════════════════════════════════

✔  DATA_PROVIDER = datagolf
✔  DATAGOLF_API_KEY = abc123… (set)
   Training through: 2025-06-08

── Step 1: Fetching player list …
   ✔  598 players returned from DataGolf

── Step 2: Fetching current season schedule …
   ✔  47 events in 2025 season
      in-progress: 1  upcoming: 12  completed: 34

── Step 3: Fetching live field …
   ✔  156 players in current field (the Memorial Tournament)

── Step 4: Training calibrated GBDT model …
   ✔  Model registered:   golf_v1 @ a3f8c2d1b0e4
      Brier (win, calibrated): 0.0148

✔  Bootstrap complete!
```

### Re-train after new events complete

Run any time to update the model with fresh results:

```bash
fly ssh console -C "python -m app.cli.train"
```

---

## 6. Local development

```bash
# Full stack (Postgres + Redis + API + frontend)
docker compose up --build

# API only (if you have Postgres + Redis running locally)
cd backend && uv run uvicorn app.main:app --reload --port 8000

# Frontend only
cd frontend && npm run dev
```

### Run tests

```bash
make test          # all (backend + frontend)
make test-backend  # pytest
make test-frontend # vitest
```

### Switch to DataGolf locally

```bash
# Create backend/.env
echo 'DATA_PROVIDER=datagolf' >> backend/.env
echo 'DATAGOLF_API_KEY=<your-key>' >> backend/.env

cd backend && uv run python -m app.cli.bootstrap
```

---

## 7. Retrain model

The model is stored on the Fly.io machine's local filesystem at
`MODEL_REGISTRY_PATH` (default `./models`). On a multi-machine setup,
use a Fly volume or S3-backed storage so all machines see the same model.

**`--feature-set` defaults to `v2`, but the active model is `v3`.** Pass
`--feature-set v3` to retrain what production actually serves. Activating a
model whose feature set differs from the current active one is refused with
exit code 2, because `deps._feature_set_for_active_model` resolves the serving
extractor by the active model's hash — so activating a v2 artifact silently
repoints the entire feature pipeline. Override with
`--allow-feature-set-change` only when the swap is intended.

```bash
# Retrain the active (v3) model with all data through today
fly ssh console -C "python -m app.cli.train --feature-set v3"

# Train through a specific date (prevent look-ahead leakage)
fly ssh console -C "python -m app.cli.train --feature-set v3 --through 2025-04-06"

# Register without activating (A/B test) — the guard does not apply
fly ssh console -C "python -m app.cli.train --name golf_v2 --no-activate"
```

---

## 8. Health checks

| Endpoint | What it checks |
|----------|---------------|
| `GET /api/v1/healthz` | Liveness — app is running |
| `GET /api/v1/readyz` | Readiness — Redis reachable + an active model loads from the registry |
| `GET /api/v1/status` | Operational snapshot — active model version, its training cutoff, serving strategy, whether the configured data provider answers right now, and the most recent captured board timestamp |
| `GET /api/v1/meta/data-freshness` | Provider last-sync timestamps |

```bash
curl https://pga-analytics-api.onrender.com/api/v1/healthz
curl https://pga-analytics-api.onrender.com/api/v1/readyz
curl https://pga-analytics-api.onrender.com/api/v1/status
```

`/status` is informational and always returns 200: each sub-check is
best-effort, so one failing dependency still reports what it can about the
rest. Use `/readyz` (which returns 503 when unhealthy) for anything
automated. `provider_reachable: "unreachable"` means the DataGolf call
failed, in which case Path A serves cold-start probabilities for the whole
field.

### Is Path A actually running?

`GET /api/v1/analytics/track-record/forward` reports `events_path_a`,
`events_cold_start_only`, and `events_regime_unknown`. A graded board counts as
Path A only when more than half its field was served DataGolf-direct
(`dg_direct_count / len(outcomes)`), which is recorded on the snapshot at
serving time.

This exists because `model_version_id` cannot answer the question: it is set to
`path_a@<cold-start-model-id>` when Path A is *configured*, before any DataGolf
call happens. A board where DataGolf returned nothing looks identical by version
id while being an entirely different product (this is exactly what the
2026-07-29 caching-wrapper bug produced). A rising `events_cold_start_only` is
the alert that DataGolf coverage has silently dropped.

Snapshots written before this field existed report `null` and are counted as
`events_regime_unknown` rather than assumed healthy.

### Cold starts on the free tier

The Render free instance spins down after ~15 min idle. Two mitigations,
both optional:

- `.github/workflows/keep-warm.yml` pings `/healthz` every 10 minutes. One
  always-on service fits inside the free plan's 750 instance-hour monthly
  allowance. GitHub pauses scheduled workflows after 60 days without repo
  activity, and cron firing is not minute-precise, so treat this as a
  strong reduction in cold-start odds rather than a guarantee.
- `scripts/warm_demo.sh [base_url]` wakes the container, prints `/status`,
  and builds the current event's board (the slower of the two costs, since
  an uncached board also pays a rate-limited DataGolf fetch). Boards are
  cached for 6h after that.

---

## 9. Troubleshooting

### "No active model registered" on /predictions

The fallback `ConstantModel` is serving. Run `python -m app.cli.train` and
check `MODEL_REGISTRY_PATH` is writable and persistent.

### Benchmark page shows "DataGolf API not connected"

`DATA_PROVIDER` is still `mock`. Set `DATA_PROVIDER=datagolf` and restart
the app: `fly deploy` or `fly machine restart`.

### Players/tournaments return empty data

If using mock, the data is generated in-memory on startup — always populated.
If using datagolf, the Redis cache may be cold. Check:

```bash
fly ssh console -C "python -m app.cli.bootstrap --skip-train"
```

### Sentry not receiving events

Confirm `SENTRY_DSN` is set: `fly secrets list`. The DSN must be the full
`https://...@sentry.io/...` URL, not just the project slug.

### Fly cold start latency

The default `fly.toml` uses `auto_stop_machines = "stop"` to save cost.
For always-on: set `min_machines_running = 1` in `fly.toml` and redeploy.

### DataGolf API rate limits

DataGolf does not publish hard rate limits but recommends caching aggressively.
`DATA_PROVIDER_CACHE=true` (default) stores responses in Redis with these TTLs:

| Method | TTL |
|--------|-----|
| Players | 24 h |
| Tournaments | 6 h |
| Field | 15 min |
| Rounds | 1 h |
| Projections | 15 min |

If you hit limits, increase TTLs in `app/providers/caching.py → _TTL`.

---

## 10. Cost estimate

| Service | Tier | Monthly |
|---------|------|---------|
| Fly.io (backend) | shared-cpu-1x 512MB, auto-stop | ~$0–5 |
| Fly.io (Postgres) | 1-replica, 1GB | ~$7 |
| Vercel (frontend) | Hobby | $0 |
| Redis (Fly) | Upstash free tier or Fly Redis | $0–3 |
| DataGolf API | Basic subscription | $18–30 |
| Sentry | Developer plan | $0 |
| **Total** | | **~$25–45/mo** |
