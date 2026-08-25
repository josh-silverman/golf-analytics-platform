# PGA Analytics Platform — Runbook

Operational reference for deploying, configuring, and troubleshooting the
platform. Read this top-to-bottom on first setup; use the section headings
for quick reference thereafter.

---

## 1. Quick-start checklist

| Step | Command / action |
|------|-----------------|
| 1 | Buy DataGolf API key at [datagolf.com/api-access](https://datagolf.com/api-access) |
| 2 | Deploy backend → Render blueprint (§ 3) |
| 3 | Deploy frontend → Vercel (§ 4) |
| 4 | Set secrets (§ 2) |
| 5 | Run the bootstrap pipeline locally, commit the model (§ 5, § 7) |
| 6 | Visit `/benchmark` to confirm live data is flowing |

---

## 2. Environment variables / secrets

### Backend (Render environment)

Non-secret values are declared in [`render.yaml`](../render.yaml) and applied
by the blueprint. The two secrets are marked `sync: false` there and are pasted
into the Render dashboard, never committed:

- `DATAGOLF_API_KEY`
- `ADMIN_API_TOKEN`

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATAGOLF_API_KEY` | ✅ when `DATA_PROVIDER=datagolf` | — | DataGolf subscription key |
| `ADMIN_API_TOKEN` | ✅ in production | — | Gates the archive, capture and track-record admin endpoints. Absent ⇒ those routes answer 404. |
| `BOARD_ARCHIVE_BACKEND` | ✅ in production | `file` | `redis` on Render: the free-tier disk is ephemeral, so a file-backed archive would not survive a redeploy. |
| `DATABASE_URL` | — | — | Unused. `render.yaml` provisions no Postgres and the serving path never touches one; `app/db/` is vestigial (ledger §3.4). Listed as required until 2026-08-25, which is the assumption that broke `/readyz` in `f265744`. |
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
> (`/api/*` → `https://pga-analytics-api.onrender.com/api/*`), so no backend URL
> env var is needed at build time.

---

## 3. Backend deployment (Render)

Render is the live path. Deployment is blueprint-driven from
[`render.yaml`](../render.yaml) at the repo root, and `autoDeploy: true` means
**a push to `main` redeploys the API**. There is no deploy CLI step.

### First deploy (one time)

Render dashboard → New → Blueprint → connect this repo. Render reads
`render.yaml` and prompts for the two `sync: false` secrets, which are never
committed:

- `DATAGOLF_API_KEY`
- `ADMIN_API_TOKEN` — gates the archive and track-record admin endpoints

The blueprint provisions two services: the `pga-analytics-api` web service
(built from `backend/Dockerfile`, health check `/api/v1/healthz`) and the
`pga-redis` Key Value instance.

**The Key Value instance is deliberately on the paid Starter plan.** Free Key
Value has no persistence, so any restart erased the forward archives — the one
loss the platform cannot recover by recomputing. After the first apply, also
set persistence to "Journal + Snapshot" in the dashboard; that is not
expressible in `render.yaml`.

### Subsequent deploys

```bash
git push origin main   # autoDeploy picks it up
```

Watch the deploy in the Render dashboard, then confirm with the health checks
in §8. A deploy that lands after Wednesday 21:00 UTC misses that week's capture
window entirely — see [ledger.md](ledger.md) §3.7.

### Database migrations

**There are none to run.** `render.yaml` provisions no Postgres, and the
serving path (Path A + model registry + DataGolf provider) never touches a
database. `backend/app/db/` and the alembic migration are vestigial and are
kept deliberately as a warning, not as a live schema — read
[ledger.md](ledger.md) §3.4 before wiring anything into them. `/readyz` was
broken once by assuming this schema was live.

### Scale

Free tier: one instance, spun down after ~15 min idle. Cold-start mitigations
are in §9. Scaling is a plan change in the Render dashboard, not a config
value here.


## 4. Frontend deployment (Vercel)

### First deploy

```bash
cd frontend
npx vercel --prod
```

Vercel auto-detects Vite. The `vercel.json` at the repo root configures:
- API proxy: `/api/*` → `https://pga-analytics-api.onrender.com/api/*`
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

Run it **locally**, not on the server. Bootstrap trains a model, and per §7
the registry is shipped through git rather than written on the instance:

```bash
cd backend
# backend/.env supplies DATAGOLF_API_KEY and DATA_PROVIDER=datagolf
uv run python -m app.cli.bootstrap
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

Step 4 registers a model into `backend/models/`. To ship it, commit and push
it — see §7, which is the full procedure and the one to follow for any retrain
after the first. Note that bare `train` defaults to `--feature-set v2`, which
is **not** the active model and does change Path A cold-start serving; §7
explains why that matters.

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

**The registry is in git, not on the server.** `backend/models/` is tracked
(23 files, ~8 MB), `.dockerignore` does not exclude it, and the prod stage does
`COPY . .` into `/app` where `MODEL_REGISTRY_PATH=./models` resolves. So the
model the API serves is **whatever is committed at image-build time**, and
retraining is a local action followed by a commit:

```
train locally  ->  commit models/  ->  push to main  ->  Render rebuilds  ->  new model served
```

There is no server-side step, and there must not be one. Training inside the
container would fail three ways: the free-tier filesystem is ephemeral, so the
artifact dies on the next restart; the 512 MB instance runs one worker at
~150 MB idle and a GBDT fit over several seasons would not fit beside it; and
an artifact that only ever existed in a container has no commit behind it,
which breaks the traceability from `model_version_id` back to a reviewable
change that [ledger.md](ledger.md) §2.6 depends on.

### The policy

Retraining is allowed **only between Monday settlement and Wednesday capture**
(roadmap Decisions §3). Because the deploy is part of the procedure, "before
Wednesday capture" means the Render build must be **live before Wednesday
21:00 UTC**, not merely pushed. See [ledger.md](ledger.md) §3.7.

### Two models are live at once — read before choosing `--feature-set`

The registry serves two artifacts by different selection rules, and this is the
easiest thing to get wrong:

| Role | Selected by | Reported as |
|---|---|---|
| Active stacked model | `_active.txt` | `/status`'s `model_version_id` |
| Path A cold-start | newest **v2** by `training_data_through`, **ignoring `_active.txt`** | boards' `path_a@<id>` |

Currently `_active.txt` is `0d2efade42ba` (v3) and cold-start resolves to
`d69cf2a7323f` (v2), both trained through 2026-06-30.

**The trap: `--no-activate` does not mean "no production effect".** Cold-start
selection is `_latest_v2_cold_start()` in `api/v1/deps.py`, which filters by
feature-set hash and takes the newest `training_data_through`. Registering *any*
v2 with a more recent through-date changes what Path A serves on the next
deploy, whether or not you activated it. `--no-activate` only skips writing
`_active.txt`, which the v2 path never reads. This is deliberate (the docstring
says a future v2 retrain should flow through automatically), but it means a v2
trained "just to compare" is a production change.

`--feature-set` defaults to **v2** while the active model is **v3**, so a bare
`train` is both the wrong feature set for `/status` *and* a live change to
cold-start serving. Activating a model whose feature set differs from the
active one is refused with exit 2, because `deps._feature_set_for_active_model`
resolves the serving extractor by the active model's hash. Override with
`--allow-feature-set-change` only when the swap is intended.

### Procedure

```bash
cd backend
# Uses backend/.env for DATAGOLF_API_KEY; no server access involved.

# 1. Retrain the active stacked model.
uv run python -m app.cli.train --feature-set v3 --through 2026-08-24

# 2. Retrain the Path A cold-start model, if you want it moved too.
#    Registering this at all changes cold-start serving — see the trap above.
uv run python -m app.cli.train --feature-set v2 --through 2026-08-24 --no-activate

# 3. Confirm what you are about to ship.
cat models/golf_v1/_active.txt
git status --short models/
```

Pick `--through` as the **last completed Sunday**, not today. It sets
`training_data_through`, which is what certifies a board out-of-sample
(`is_out_of_sample`). A through-date past an upcoming event's start makes
future boards for that event un-gradeable.

Existing archived boards are unaffected: each snapshot stores its own
`model_version_id` and `model_trained_through`, so retraining never
retroactively re-grades the record. Only boards captured *after* the deploy
change.

```bash
# 4. Commit and deploy. Never delete old versions — ledger §2.6, and the v2
#    cold-start model is a live dependency, not just history.
git add backend/models/
git commit -m "retrain: golf_v1 v3 through 2026-08-24"
git push origin main        # autoDeploy rebuilds

# 5. Verify the deploy actually carries it.
curl -s https://pga-analytics-api.onrender.com/api/v1/status | jq '.model_version_id'
```

Step 5 must return the id now in `_active.txt`. If it returns the old one the
build has not finished or has failed — check the Render dashboard before
Wednesday's deadline.

**Expect `/status` and the boards to disagree, and do not treat that as a
failure.** `/status` reports the registry-active v3 model; boards are stamped
`path_a@<v2 cold-start id>`. Different identifiers, both authoritative for
different things. `archive/inspect` shows what a board actually carried.

Each retrain adds roughly 600 KB to the repo (one `artifact.pkl` plus
`metadata.json`). At the Monday-to-Wednesday cadence that is a few MB a year,
which is acceptable; revisit if it ever stops being.

### If retrains become frequent

A `workflow_dispatch` job could train in Actions and commit the artifact back.
It is not built, and deliberately: it needs `DATAGOLF_API_KEY` in Actions and a
bot with write access to `main`, to automate an action that happens at most
weekly and is a deliberate human decision under the policy above. The local
path costs one command and keeps writes human-triggered.


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

The fallback `ConstantModel` is serving, which means the image has no active
model. Check `backend/models/golf_v1/_active.txt` is committed and names a
directory that is also committed — a version registered locally but never
`git add`ed will not exist in the deployed image. `MODEL_REGISTRY_PATH` needs
to be readable, not writable: nothing writes to it at runtime.

### Benchmark page shows "DataGolf API not connected"

`DATA_PROVIDER` is still `mock`. `render.yaml` sets it to `datagolf`, so this
means the running instance predates that or the value was overridden in the
dashboard. Fix it in the Render dashboard (Environment tab) and use Manual
Deploy → Restart service.

### Players/tournaments return empty data

If using mock, the data is generated in-memory on startup — always populated.
If using datagolf, the Redis cache may be cold. Two different things to check,
and they need different commands.

Warm the **production** cache through the public API, since the free tier has
no shell:

```bash
scripts/warm_demo.sh
```

Diagnose the **provider** itself locally — this validates the DataGolf key and
data readiness without training anything:

```bash
cd backend && uv run python -m app.cli.bootstrap --skip-train
```

The local run tells you whether DataGolf is answering; it cannot fix a cold
production cache, because it warms your machine's Redis rather than Render's.

### Sentry not receiving events

Confirm `SENTRY_DSN` is set in the Render dashboard (Environment tab). The
DSN must be the full `https://...@sentry.io/...` URL, not just the project
slug.

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

### Restore the forward archives after a Key Value wipe

The board and matchup archives live in the Render Key Value instance. If
that instance loses its data (free plans have no persistence; paid plans
can still be reset), the record is restored from the private ledger repo:

```bash
# 1. Grab the last committed dump (private repo — DataGolf ToS: never public).
git clone git@github.com:josh-silverman/pinpoint-ledger.git

# 2. POST it back. Idempotent and first-write-wins: an import only fills
#    gaps, it can never overwrite a snapshot the live store still holds.
curl -fsS -X POST \
  -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data @pinpoint-ledger/golf-analytics/archive-export.json \
  https://pga-analytics-api.onrender.com/api/v1/analytics/archive/import

# 3. Confirm: boards_stored + boards_skipped should equal the dump's board
#    count, and /analytics/track-record/forward should grade the same
#    events as before the wipe.
```

Exports are written by `.github/workflows/archive-export.yml` (nightly +
after every scheduled capture + manual dispatch). If the wipe happened
between a capture and its export, that snapshot is gone; everything up to
the last commit in `pinpoint-ledger` comes back.

---

## 10. Cost estimate

| Service | Tier | Monthly |
|---------|------|---------|
| Render (backend web) | free, spins down after ~15 min idle | $0 |
| Render (Key Value) | **Starter** — free has no persistence, see § 3 | ~$10 |
| Vercel (frontend) | Hobby | $0 |
| Postgres | none provisioned; the serving path never uses one | $0 |
| DataGolf API | Basic subscription | $18–30 |
| Sentry | Developer plan | $0 |
| **Total** | | **~$28–40/mo** |
