# Repo audit — pre-ledger baseline (2026-08-19)

Audit performed on `main` at `0a425c9`, working tree clean, up to date with
`origin/main`. Every claim below is tagged **[observed]** (read directly from
code, config, git history, or a command run during the audit) or
**[inferred]** (a conclusion drawn from those observations without a comment
or test confirming intent).

---

## 1. Repo map

### Layout

```
backend/app/
  api/v1/        FastAPI routes: predictions, analytics (track records,
                 matchup capture/grade, calibration), players, tournaments,
                 betting, health, meta
  providers/     DataProvider protocol; DataGolfProvider; MockDataProvider;
                 CachingProviderWrapper; factory selects via DATA_PROVIDER
  services/      catalog (provider passthrough), features, predictions,
                 board_archive, forward_track_record, track_record,
                 matchup_line_record, betting
  features/      versioned, content-hashed feature sets (v2 SG-only,
                 v3 + DataGolf meta-features)
  ml/            trainer, calibration, rolling-origin backtest w/ block
                 bootstrap, registry, diagnostics, rank_v1 research harness
  cli/           train, backtest, diagnose, bootstrap (all manual)
  db/            SQLAlchemy models + alembic initial migration — see §1.4
backend/models/           git-tracked filesystem model registry (23 files)
backend/prediction_boards/  local-only (untracked) file board archive
backend/tests/            344 tests total; 307 fast-lane, 37 marked slow
frontend/                 React 19 + Vite; leaderboard is the hub page
.github/workflows/        ci.yml, keep-warm.yml, matchup-capture.yml
docs/                     architecture docs, runbook, project summary/brief
tournament-analyses/      weekly analyst reports graded post-event
```

### 1.1 Data flow, raw source → prediction output [observed]

1. **Source**: DataGolf API via `providers/datagolf/datagolf_provider.py`
   (production, `DATA_PROVIDER=datagolf` in `render.yaml`) or a seeded
   `MockDataProvider` (dev/tests). A `CachingProviderWrapper` sits in front
   (Redis-backed).
2. **Serving** (`GET /api/v1/predictions/{tournament_id}`,
   `app/api/v1/predictions.py`): `PredictionService.predict_tournament`
   caps `as_of` at event eve, extracts field-wide features, then under the
   default `serving_strategy="path_a"` serves DataGolf's own five-market
   probabilities for covered players and the registered SG-only model for
   uncovered ones. Both flow through `coherent_outcomes` +
   `normalize_field`. Finished boards are Redis-cached 6h.
3. **Capture**: on the first serve of a not-yet-completed event, the board
   is written immutably to the board archive (`_capture_board`,
   predictions.py:60-90). First write wins (`SET NX` in Redis, existence
   check on file). This is the only live capture trigger — it is **lazy**;
   nothing schedules it.
4. **Settlement/grading**: `GET /analytics/track-record/forward` re-reads
   the archive, re-fetches each event's field (with final positions) from
   the provider at request time, and grades only snapshots whose model
   `trained_through` is strictly before the event start. Brier skill vs.
   the field base rate, per market, with a block-bootstrap 90% CI over
   events. No-cut events are excluded from the make-cut aggregate.
5. **Matchups**: a parallel capture-and-grade loop
   (`services/matchup_line_record.py`) snapshots DataGolf's matchup feed
   weekly via GitHub Actions cron and grades it once events settle in
   DataGolf's historical-odds archive.

### 1.2 Models: trained and stored where [observed]

- Training is manual: `uv run python -m app.cli.train` →
  `train_calibrated_and_register` → filesystem `ModelRegistry` at
  `backend/models/` (git-tracked, including pickles). `_active.txt` names
  the serving version.
- `ModelVersion` records `feature_set_hash`, `training_data_through`,
  `hyperparameters`, `metrics`, `trained_at`. `version_id` is a
  deterministic 12-char SHA-256 of (feature hash, cutoff, hyperparameters),
  so retraining with identical inputs is idempotent.
- **Not recorded anywhere: the git SHA of the training code.** Neither
  `ModelVersion` nor `BoardSnapshot` carries one.
- Serving stamps boards `path_a@<version_id>`; `dg_direct_count` on the
  snapshot distinguishes a healthy Path A board from a whole-field
  cold-start (post-`a57efd9`).

### 1.3 Evaluation surfaces [observed]

| Surface | Where | Nature |
|---|---|---|
| Rolling-origin backtest | `app/ml/backtest.py`, `app/cli/backtest.py` | Offline, leakage-controlled (train strictly before test window, as-of capped features), Brier/log-loss/ECE + skill vs. base rate, block-bootstrap CIs |
| Diagnostics | `app/cli/diagnose.py`, `app/ml/diagnostics.py`, `backend/diagnostics/*` | Per-player error export, permutation importance, research scripts |
| Calibration | `app/ml/calibration.py`, `/analytics/calibration` | Reliability bins per market |
| Active-model track record | `/analytics/track-record`, `services/track_record.py` | Pre-event boards on completed events, but **potentially in-sample on the model** (documented in-code) |
| Forward OOS record | board archive + `services/forward_track_record.py` + `/analytics/track-record/forward` | Immutable pre-event snapshots, OOS-certified by training cutoff, bootstrap CI |
| Matchup line record | `services/matchup_line_record.py` + `/analytics/matchups/*` | Weekly immutable capture of book prices + DataGolf line; graded vs. settled outcomes at EV thresholds 0/2/5¢ |

### 1.4 Postgres is not used by the application [observed]

No module outside `app/db/` imports `app.db` (grep over `app/`,
2026-08-19). `render.yaml` deploys no Postgres and says so explicitly.
`CatalogService` reads from the provider directly; its docstring calls the
DB swap a future seam. The alembic initial migration and
`app/db/models.py` exist but are vestigial. Commit `f265744` ("/readyz
permanently reported not-ready on a DB it never uses") confirms this was
already recognized.

### 1.5 Scheduling and triggers today [observed]

| What | Trigger | Evidence |
|---|---|---|
| CI (ruff, mypy, pytest fast lane, frontend lint/tsc/vitest/build, docker builds) | push to main + PRs | `.github/workflows/ci.yml` |
| Keep-warm ping of `/healthz` | cron every 10 min, 12:00–04:00 UTC | `keep-warm.yml` (budgeted against Render free 750 h/mo) |
| Matchup line capture | cron Wed 21:00 + Thu 11:00 UTC retry, + manual | `matchup-capture.yml`; `ADMIN_API_TOKEN` repo secret **set 2026-08-19**; first dispatch failed, second succeeded 2026-08-19 20:07 UTC (`gh run list`) |
| Prediction-board capture | **lazy** — first pre-event serve of the board | `predictions.py:124` |
| Forward backfill (post-hoc board reconstruction) | manual admin `POST /analytics/track-record/forward/backfill` | `analytics.py:171` |
| Retraining | manual CLI | `app/cli/train.py`, runbook §7 |
| Settlement/grading | on-request GET, recomputed from live provider each time (some Redis caching) | `analytics.py` |

There is **no scheduled job** for board capture, backfill, settlement,
grading, or retraining.

### 1.6 Tests and CI [observed]

`uv run pytest -m "not slow"` on this machine: **307 passed, 37
deselected, 14.3s** (run during this audit). CI runs the same fast lane
plus mypy `--strict` and ruff. Slow lane (calibration validation,
end-to-end) is excluded from CI and runs only manually. Regression tests
exist for the past incidents (caching-wrapper delegation, no-cut
contamination, train-CLI feature-set guard).

---

## 2. Your claims, verified

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Personal PGA analytics platform producing probabilities across several betting markets | **Confirmed** | Five outcome markets (win/top-5/10/20/make-cut) in `services/predictions.py`; betting-edge endpoint; matchup product line |
| 2 | Offline evaluation exists: backtesting, bootstrap significance, calibration | **Confirmed, and it works** | `app/ml/backtest.py` (rolling-origin, `_bootstrap_skill_ci`), `app/ml/calibration.py`, CLIs; exercised by `tests/test_backtest.py` et al.; suite passes (§1.6). Not aspirational. |
| 3 | **No live record of what the platform predicted and how it turned out** | **Contradicted** | A forward, out-of-sample prediction ledger already exists and is deployed: immutable pre-event board snapshots (`services/board_archive.py`, Redis-backed in prod per `render.yaml`), graded at `/analytics/track-record/forward`, shown on the frontend. A second forward record for matchup lines went live 2026-08-19 (`52e10c5`, first successful capture same day). What's missing is narrower than "no record" — see §3. |
| 4 | "I keep changing things without a reliable way to know whether a change helped" | **Partially true** | The backtest harness is exactly that instrument offline, and the repo's history shows it being used as the A/B gate (README, closed-experiment docs). Forward, the record is young (weeks old, `_MEANINGFUL_EVENTS = 20` heuristic not yet reached) and its early events straddle the 2026-07-29 caching-bug fix, so the aggregate is regime-split rather than clean. |
| 5 | `fix/no-cut-market-contamination` exists, tested but unmerged; a README figure depends on it | **Contradicted (already merged)** | Branch exists with that exact name, but it was merged into main **today**: `45b225f` (2026-08-19 15:22 -0400) merges `b092b10`/`ceb82f8`. The merge included the fix, 2 test files (~159 test lines), and the README caveat on the published make-cut figure. `origin/main` already has it. Merging changes nothing further; the branch can be deleted. |

Additional discrepancies from your framing, worth knowing:

- **Item 1 of your build list is roughly 60% built.** Immutable pre-event
  predictions: built. Settled-after grading: built but recomputed from the
  live provider, not stored (§4, R3). Named baselines: only field base
  rate. Model registry: built, minus git SHA. See §3.
- **Your memory note that matchup grading "needs ADMIN_API_TOKEN gh
  secret"**: resolved — the secret was added 2026-08-19 and the workflow
  succeeded on manual dispatch the same day.
- **Under Path A, "grade the model against DataGolf" is confounded**: for
  ~95% of a covered field the served numbers *are* DataGolf's (rescaled by
  field normalization). A DataGolf baseline in the forward record is only
  a genuine model-vs-DataGolf comparison on cold-start players; framing
  matters when you design the baseline columns. [inferred from
  `PathASource` semantics]

---

## 3. What exists to build the ledger on vs. what's missing

### Already built (extend, don't duplicate)

- **`BoardSnapshot` + `BoardArchive`** (`services/board_archive.py`):
  immutable first-write-wins snapshots keyed `(tournament_id,
  model_version_id)`, file + Redis backends behind one protocol,
  forward-compatible deserialization, provenance fields
  (`model_version_id`, `feature_set_hash`, `model_trained_through`,
  `as_of`, `captured_at`, `source`, `dg_direct_count`). This *is* the
  prediction ledger's skeleton.
- **Forward grader** (`services/forward_track_record.py`): OOS admission
  rule, per-market Brier skill, block-bootstrap CI, no-cut exclusion,
  serving-regime split.
- **Matchup archive** (`services/matchup_line_record.py`): the same
  immutability contract applied to a second record; proves the pattern
  generalizes.
- **Model registry** (`app/ml/registry.py`): deterministic version ids,
  metadata JSON, git-tracked artifacts.
- **Operational patterns**: admin-token-gated POST endpoints + GitHub
  Actions cron (matchup-capture.yml) — the exact template for scheduled
  board capture and settlement.
- **Backfill** (`POST /track-record/forward/backfill`): idempotent
  post-hoc seeding, already regression-tested.
- **Provider odds surface**: `DataProvider.get_outright_odds` and the
  de-vig logic in `services/betting.py` already exist — the ingredients
  for a closing-line baseline, minus the capture job.

### Genuinely missing (the gap between what exists and your item 1)

1. **Git SHA provenance.** Nothing records the code revision that trained
   a model or served a board.
2. **Immutable settlement records.** Grades are recomputed from the live
   provider on every request; results are never snapshotted. A provider
   data revision (or outage) silently changes the historical record.
3. **Named baselines.** The forward grader scores only "vs. field base
   rate". No DataGolf-raw column, no closing-market-implied column, and
   nothing captures closing lines at all.
4. **Scheduled capture.** Board capture depends on someone loading the
   leaderboard before the event. Keep-warm pings `/healthz` only and does
   not build boards, so an unattended week can miss live capture entirely
   (backfill can reconstruct it, but that is a weaker artifact — R2).
5. **Grader ledger-hygiene**: per-tournament dedup across model versions
   and a captured/backfilled split in reporting (R1, R2).
6. **Durability/export of the archive itself** (R4).

---

## 4. Risks to a trustworthy live record

- **R1 — Double-counting events across model versions [observed in code].**
  `compute_forward_track_record` iterates snapshots, not tournaments
  (forward_track_record.py:132). The archive key is `(tournament,
  model_version)`, so retraining mid-week captures a *second* snapshot of
  the same event, and both are graded as separate events/bootstrap blocks.
  Hasn't happened yet [inferred: local archive has one version per event],
  but weekly retraining automation (your item 2) makes it inevitable
  without a dedup rule.
- **R2 — Backfilled boards are reconstructions, pooled with live captures
  [observed].** `source="backfilled"` snapshots are rebuilt by *current*
  code over DataGolf's pre-event archive. Leakage-safe on data, but code
  drift means they are not what production would have served at the time,
  and the grader never reads `snap.source` — the headline number mixes
  the two silently.
- **R3 — Settlement is re-derived, not recorded [observed].** See §3.2.
  Also means grading requires the provider to be up and the subscription
  to be active; the record is not self-contained.
- **R4 — The production ledger lives in one free-tier Redis with no
  export [observed config, inferred risk].** `render.yaml` stores both
  archives in Render's free keyvalue instance. Keys are written with no
  TTL, but eviction policy, memory ceiling, and persistence of that
  instance are not controlled by the repo and are unverifiable from here.
  Anyone/anything with Redis access can `DEL` or overwrite keys; `SET NX`
  is a convention, not a guarantee. There is no dump/export endpoint and
  no backup job. This is the single largest threat to the record: total,
  silent, irrecoverable loss.
- **R5 — Predictions could be regenerated after the fact only via
  archive-store access [observed].** The API surface itself is safe:
  capture refuses completed events, first-write-wins is enforced at the
  store, and the backfill endpoint honors both. The residual overwrite
  path is direct Redis/filesystem access. Mitigation is the same as R4:
  periodic exports pinned somewhere append-only (e.g., git commits, which
  timestamp them independently).
- **R6 — The forward record is mostly grading DataGolf, not the in-house
  model [inferred].** Under Path A a covered field is ~95% DataGolf-direct.
  The regime split (`events_path_a` etc.) makes this visible but the
  market skill columns still pool both sources. Fine for "what the
  platform served", misleading if read as "our model's skill". Baseline
  columns (§3.3) are the fix.
- **R7 — Lazy capture timing is uncontrolled [observed].** `as_of` is
  capped at the eve, but the capture can happen any number of days before
  the event, whenever traffic arrives. Snapshot-to-snapshot comparability
  (and any future closing-line comparison) benefits from a scheduled
  capture at a consistent time.
- **R8 — Scheduled workflows are best-effort [observed, documented
  in-workflow].** GitHub disables crons after 60 days of repo inactivity;
  runs can be delayed. Acceptable for now, worth an alerting hook when
  automation carries the weekly cycle.
- **R9 — Local dev file archive diverges from prod [observed].**
  `backend/prediction_boards/` (events 100, 524) is untracked and
  machine-local; production truth is in Render Redis. Any audit of "what
  was predicted" must query production, and nothing currently makes that
  easy (§3.6).

Leakage exposure in the offline harness looks well-controlled [observed]:
train-strictly-before-window, as-of-capped features, field normalization
applied in backtest as in serving (`df146fd`), no-cut exclusion in both
graders, and regression tests around each. No contradicting evidence found.

---

## 5. Branch inventory

`origin` has only `main`. All 22 local branches are **fully merged into
main** (`git branch --merged main` lists every one; `--no-merged` is
empty). None is ahead of main; all are safe to delete. Notables:

| Branch | State |
|---|---|
| `fix/no-cut-market-contamination` | Merged today via `45b225f`; included the metrics fix, tests, and the README figure caveat. Your "unmerged" belief is stale as of this afternoon. |
| `rank-native-model`, `phase1-historical-archive` | Closed research programs, merged; kept as history |
| 20 others (`feat/*`, `fix/*`, `style/*`, `chore/*`, `refactor/*`) | All merged UI/infra work |

Working tree clean, no stashes, `main` == `origin/main` at `0a425c9`.

---

## 6. Open questions for Josh

1. **Render Redis durability (drives R4 urgency).** Can you check in the
   Render dashboard what the free keyvalue plan gives you: maxmemory
   policy (noeviction vs. LRU), memory ceiling, and whether it persists
   snapshots? If eviction is possible, the export job (roadmap unit 0)
   should ship before anything else.
2. **DataGolf subscription scope.** ~~Matchup capture (betting-tools) worked
   today, so the key likely covers `betting-tools/outrights` too — can you
   confirm?~~ **Resolved 2026-08-21: yes.** Probed the live endpoint with the
   production key across all five markets (`win`, `top_5`, `top_10`,
   `top_20`, `make_cut`); every one returned 200 with a full board. Coverage
   is 12-15 books depending on market. Two shapes worth recording, both
   found by probing rather than from the docs: a market the books are not
   offering returns `odds` as a **message string**, not an empty list (BMW
   Championship, a no-cut playoff event, does this on `make_cut`), and the
   `datagolf` key inside a player row is a **nested dict** of DataGolf's own
   baseline lines, not a price string. A5 handles both.
   Related: any ToS concern with committing exported DataGolf-derived
   probabilities to a **public** repo? **Resolved: yes, so exports go to the
   private ledger repo** (A0), and the pre-existing exposure in README and
   `tournament-analyses/` is still open.
3. **Retrain cadence intent.** Weekly automated retraining interacts with
   R1 (one event, two model versions). Options: dedup rule in the grader
   (prefer earliest capture), or a capture policy (one snapshot per event,
   period). Both are small; which the ledger should treat as canonical is
   a product decision.
