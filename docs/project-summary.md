# PGA Analytics — State of the Project

A consolidated snapshot of the predictive model, the research program that
validated its performance ceiling, the architecture, and the methodology used
to reach these conclusions. This is a **reference document**, not a roadmap:
it records where the project stands as of **2026-07-01** and the evidence
behind that state.

For the prompt-validation briefing (how to judge proposed work against settled
results) see [project-brief.md](project-brief.md). For the running experimental
log see the `project_model_baseline` memory.

---

## 1. Active model and performance

### 1.1 Model identity

| Property | Value |
|---|---|
| Model name | `golf_v1` |
| Active version | `0d2efade42ba` |
| Feature set | `v3_dg_preds` (hash `18a5376f33f7…`) |
| Feature count | 18 |
| Estimator | scikit-learn `HistGradientBoostingClassifier`, one per market |
| Markets | win, top-5, top-10, top-20, make-cut |
| Calibration | per-market: sigmoid (win, top-5) + isotonic (top-10, top-20, make-cut) |
| Trained through | 2026-06-30 |
| Training examples | 26,853 (+ 8,951 held out for calibration) = 35,804 total |
| Training span | 2024+ (get-schedule) plus the 2018–2023 historical archive; 365-day recency weighting |
| Feature window | 730 days per example, computed as-of each example's date (leakage-safe) |
| Deployment | not necessarily deployed; `fly.toml` targets `pga-analytics-api` (iad) with `DATA_PROVIDER=datagolf` |

The model is **not** the latest thing tried — it is the latest thing that
*passed the promotion gate*. Several later experiments were tested and rejected
(Section 2); the active version is the one with validated, reproducible skill.

### 1.2 Hyperparameters

```
model_family        sklearn.HistGradientBoostingClassifier
max_iter            200
max_depth           3
learning_rate       0.05
min_samples_leaf    80          # the one validated tuning win (was 20)
l2_regularization   0.0
random_state        0
recency_half_life   365 days    # exponential decay on training-example weight
```

All five per-market estimators share this configuration. `min_samples_leaf=80`
was the only hyperparameter changed from a default through the entire research
program, and it is the only validated model-quality improvement those programs
produced (Section 2.3).

### 1.3 Feature set (`v3_dg_preds`, 18 features)

The first fourteen features (below) are derived purely from a player's
strokes-gained (SG) round history — this is the `v2_field_relative` core, which
`v3_dg_preds` extends without altering (its hash `bc91c96027e8` is unchanged).
The four new features are **external-model meta-features** (see the block after
the SG features). There is still no player identity, no course attribute, and no
weather in the model — those were all tested and did not clear the gate.

**Absolute skill (5)** — time-decayed (60-day half-life) weighted mean of
per-round SG in each category, shrunk toward a below-average prior worth 5
pseudo-rounds so thin histories do not read as "average":

- `sg_ott_rating`, `sg_app_rating`, `sg_arg_rating`, `sg_putt_rating`, `sg_total_rating`

**Form (1)** — `form_index`: recent-8-round SG-total mean minus
last-50-round mean (heating up vs. baseline).

**Field-relative skill (5)** — each player's skill *minus the field mean* in
that category, so the model sees each player relative to the field they
actually face. This was the single biggest improvement ever made:

- `field_rel_sg_ott`, `field_rel_sg_app`, `field_rel_sg_arg`, `field_rel_sg_putt`, `field_rel_sg_total`

**Field / confidence context (3)**:

- `field_strength` — field mean SG-total (event quality)
- `round_count` — sample size behind the skill estimate
- `score_volatility` — std of recent per-round SG-total

**External-model meta-features (4)** — DataGolf's *own* pre-tournament model
probabilities for this player-event, folded in as inputs (model-stacking, not a
transform of our SG data). Source is DataGolf's Pre-Tournament Predictions
Archive, `baseline_history_fit` column only:

- `dg_make_cut`, `dg_top_20`, `dg_top_10` — DataGolf's pre-event probability for
  each headroom market (`win` is excluded as coarse)
- `has_dg_pred` — 1.0 when a prediction exists for this player-event, else 0.0

These encode course-fit, field composition, and DataGolf's talent model —
orthogonal to the SG-rolling features (validated: Section 2.7). Leakage-safe:
the archived predictions are genuine frozen pre-event snapshots (not refits),
and the post-event `fin_text` DataGolf staples onto each record is **never
read** (dropped with an explicit assertion in the provider). Cold-start (a
2018–2019 event with no archive, or a player missing from an event) yields
`NaN`, never 0.0 — `HistGradientBoostingClassifier` routes NaN natively — with
`has_dg_pred=0.0` as the paired indicator.

Field-relative features are computed by a **two-pass field extraction**
(`FeatureExtractor.extract_field`): compute each player's absolute features →
average across the field → recompute as margins vs. the field mean. The DG
meta-features are fetched once per event and attached to the same contexts. The
same code path runs in training, serving, and backtesting — this is the
train/serve-parity invariant the whole feature layer exists to protect. For DG
predictions specifically, parity holds across two sources: completed/historical
events read the immutable archive, the current upcoming event reads the live
`pre-tournament` endpoint, and both return the identical
`{player_id: {make_cut, top_20, top_10}}` shape.

### 1.4 Validated performance ceiling (per market)

Out-of-sample, from the rolling-origin backtest of the active model
(`0d2efade42ba`), 10 most-recent completed events, 1,147 predictions, trained
through 2026-04-29 (34,657 training examples). The 90% confidence interval is
from the block-bootstrap infrastructure (Section 3.2), resampling whole events
with replacement. The prior `v2_field_relative` skill is shown for reference —
the v3 DG meta-features (Section 2.7) lifted every trustworthy market.

| Market | Base rate | Brier | Brier skill vs base rate | 90% CI (block-bootstrap) | (v2 skill) | Verdict |
|---|---|---|---|---|---|---|
| win | 0.9% | 0.0086 | +0.002 | **[−0.005, +0.009]** | −0.009 | straddles 0 — no edge |
| top-5 | 5.1% | 0.0470 | +0.022 | **[−0.060, +0.100]** | +0.018 | straddles 0 — noisy |
| top-10 | 10.0% | 0.0832 | +0.078 | **[+0.035, +0.109]** | +0.040 | lower CI > 0 — genuine skill |
| top-20 | 20.5% | 0.1399 | +0.141 | **[+0.115, +0.166]** | +0.088 | lower CI > 0 — genuine skill |
| make-cut | 62.6% | 0.1766 | +0.246 | **[+0.153, +0.350]** | +0.181 | lower CI > 0 — genuine skill |

Ranking quality: Spearman(win-prob, finish) +0.301, mean winner predicted rank
32.2, winner-in-top-5 20% (all improved or flat vs the v2 model's +0.291 / 33.7).

Held-out calibrated Brier from the registered artifact (a per-model random split
of its own training set — **not** comparable across models with different
training composition; see Section 2.6): win 0.0086, top-5 0.0447, top-10 0.0824,
top-20 0.1454, make-cut 0.1998.

**Brier skill score** = `1 − model_brier / base_rate_brier`. Positive means the
model beats predicting the field-average rate for everyone. It does **not**
mean beating a sportsbook — that is a far higher bar the model does not clear
(Section 1.5).

### 1.5 Honest scope — which markets to trust

- **make-cut and top-20 are trustworthy.** Their lower CI bounds are clearly
  above zero (+0.153 and +0.115 under the v3 model). These markets carry real,
  reproducible skill over the naive baseline and are where the model's analytic
  value lives. top-10 is now also genuine (lower CI +0.035 under v3, up from the
  v2 model's +0.001 boundary) — the DG meta-features lifted it clear of the
  margin.
- **win, top-5 are intentionally coarse.** Their skill CIs straddle
  zero. Winner prediction in particular has ≈0 skill and is near a practical
  ceiling: its driver is week-of variance (form, draw, conditions) that the
  model's player-history features cannot recover. The win market also has very
  few positives (~60 winners across the training set), so it is data-starved by
  construction.
- **The model does not beat a sharp sportsbook on any market.** This was
  verified live (RBC Canadian Open) against real DataGolf book odds: raw win
  probabilities were coarse (6 distinct values across 147 players) and
  individual player ratings diverged from the book by amounts that are model
  error, not value. The Betting Edge UI is deliberately framed as a
  model-vs-market *divergence / research* view, not a +EV product.

The product framing follows from this: the Leaderboard and Player pages lead
with make-cut / top-20 / finish-distribution signal; the betting view is
explicitly a research lens with reliability caveats.

---

## 2. Research program record

The model was built in two phases. First, a short sequence of feature-
engineering wins produced the active model. Then a systematic ceiling-finding
program tested every tractable orthogonal information axis and closed each one
with the same validation discipline. The conclusion — that the model is at its
performance ceiling under the current free-data constraint — is the
**product** of that program, not an assumption.

### 2.1 Shipped improvements (validated, in the active model)

| # | Change | Outcome |
|---|---|---|
| S1 | Field-relative SG features (`v2`) | ✅ Biggest single win — fixed the model's worst pathology (could not separate winners from the pack). Lesson: orthogonal, event-level information is what helps. |
| S2 | Low-data shrinkage prior (Lever A) | ✅ Shrinks each SG category toward a below-average prior so thin histories don't read as field-average → fewer phantom edges. Leakage-safe, train/serve-identical. |
| S3 | Recency weighting (365-day half-life) | ⚠️ Kept — improved probability sharpness on every market, but did **not** improve ranking. |
| S4 | `min_samples_leaf` 20→80 | ✅ The only validated win of the ceiling programs. See 2.3. |

Reverted along the way: **Lever C** (DataGolf skill ratings injected as
serve-time priors) — created a train/serve parity trap (training used fixed
priors, serving used live ratings) and was fully removed.

### 2.2 Ceiling-test directions (all closed negative)

Each was tested read-only first, gated on the rolling backtest, and reverted
when it failed. None changed the active model. Numbered by research cycle.

| Cycle | Direction | One-line outcome |
|---|---|---|
| 1 | Lever B — longer history window | ❌ Stale rounds dragged current players down; ranking collapsed. Reverted. |
| 2 | Ceiling / upside feature | ❌ Standalone correlation but ~zero incremental value; redundant with overall SG; moved 28% of predictions as symmetric noise (net ranking change ≈ 0). Reverted. |
| 3 | Course-fit (v3, length × driver) | ❌ Course attributes existed for only ~33 hardcoded venues; thin low-signal split that hurt ranking. Reverted. |
| 4 | Experiment B — course residual structure | ❌ Read-only test: finishing residuals cluster by venue only via the known field-strength bias; course-specific affinity ≈ +0.024 (≈ noise). Residual structure is a **player main effect**, not a venue effect. Course program closed. |
| 5 | Weather pilot (`event_wind`) | ❌ Leakage-safe Open-Meteo archived-forecast wind, one event-level scalar. A/B: every market flat-to-worse (make-cut −0.007, top-20 −0.006). An event-level scalar can't reorder within-field. Reverted; weather recorded exhausted. |
| 6 | Field-shape (dispersion / depth / percentile) | ❌ Failed gate (top-20 −0.017); did not move the target weak-field residual. Field-strength residual is a player main effect, not a functional-form gap. Reverted. |
| 7 | Layoff / staleness (`days_since_last_round`) | ❌ Inconclusive: 10-event +0.017 make-cut, but 85-event null and production holdout worse. Not promoted. |
| 8 | Empirical-Bayes shrinkage (`sg_total_shrunk`) | ❌ Rejected 0/3 checks. GBDT already captures n-weighted shrinkage via `sg_total_rating` + `round_count`. Reverted. |
| 9 | Player random-effects prior (`player_resid_prior`) | ❌ Inconclusive: 10-event gate cleared (top-20 +0.013, make-cut +0.010) but production holdout make-cut regressed (+0.00127). 1/3 checks. Not promoted. See 2.4. |

The directions cluster into three exhausted spaces:

- **Player-history subspace: saturated.** Lever B, ceiling, recency, and the
  player random-effects prior all failed to add incremental ranking signal.
  ~2 latent dimensions (absolute skill, field-relative skill) already capture
  it. Re-sampling a player's own SG distribution keeps landing in the same
  subspace.
- **Course information: no orthogonal signal.** Course-fit failed on coverage;
  Experiment B showed the residual structure is a player effect, not a venue
  effect.
- **Event-level context (field-shape, weather): no signal recoverable from a
  field- or event-level scalar.** These can't reorder within a field, which is
  what ranking needs.

### 2.3 The one validated improvement — `min_samples_leaf` 20→80

The only change to clear the gate cleanly. Validated with the two-regime
discipline (Section 4.1):

- **10-event production-regime backtest** (≈7,500 training examples ≈ production
  scale): make-cut +0.010, top-20 +0.008, Spearman +0.093→+0.110, mean winner
  rank 62.8→54.8 — four of five markets and ranking improve, none regress.
- **Held-out calibrated Brier** improved on all five markets vs. the prior
  baseline: win 0.0096→0.0094, top-5 0.0495→0.0492, top-10 0.0936→0.0912,
  top-20 0.1581→0.1548, make-cut 0.2022→0.1996.
- The 85-event data-starved backtest showed an artifact (make-cut +0.033 /
  top-20 −0.009) that **reversed** at production scale — which produced the
  standing lesson: the 85-event regime trains on only ~39 events and is the
  wrong regime for regularization decisions. The 10-event + holdout agreement
  is what justified promotion.

### 2.4 Player random-effects prior — the last closed direction (2026-06-23)

This direction is recorded in detail because it directly targeted Experiment
B's strongest finding (the residual is a player main effect) and because its
closure illustrates the validation discipline.

- **Hypothesis:** the model has never been given direct access to "this player
  systematically over/under-performs their SG-predicted ranking." Add it as one
  feature: each player's leave-one-event-out mean finishing-position residual
  (predicted percentile − actual percentile), plus a `has_resid_prior`
  cold-start indicator (zero-imputed when < 3 prior events).
- **Leakage-safe construction:** residuals built from a single long-window
  diagnose pass; the per-event prior uses only the player's *other* events. The
  feature was injected via a wrapper that left the `v2` feature-set hash
  unchanged, keeping the comparison apples-to-apples.
- **Result (3-check battery):**
  - 10-event gate: **cleared** — top-20 +0.013, make-cut +0.010, Spearman −0.006.
  - 85-event cross-check: **+0.000 on every market** — structurally
    uninformative (the residual DB started at the test-window edge, so the
    feature was constant-zero in that regime's training and the GBDT could not
    split on it). Recorded honestly as "couldn't test," not "disconfirms."
  - Production holdout (the clean tiebreaker): **make-cut Brier +0.00127
    worse**, top-20 −0.00028 better.
- **Decision:** 1 of 3 → **close and revert.** The make-cut holdout regressed —
  the same pattern as the layoff false positive. The single favorable 10-event
  split was split variance, which is precisely the failure mode the
  block-bootstrap CI now guards against.

### 2.5 Infrastructure improvements (kept)

| Item | What it does |
|---|---|
| Block-bootstrap 90% CI in the backtest harness | Resamples whole events (the correct unit of variance — within-event predictions are correlated) to put a confidence interval on each market's Brier skill. New promotion rule: point estimate ≥ threshold **and** lower CI bound > 0. Directly catches the single-split false positives that cost three validation runs each in the layoff and player-random-effects cycles. |
| Schedule / valid-events cache TTL (6h) | Completed events self-heal without a container restart; previously a process-lifetime cache froze mid-tournament and never saw `in_progress → completed`. |
| Read-only diagnostics pipeline | Exports per-(player, event) predictions, feature values, permutation importances, and calibration bins. The evidence layer every ceiling-test direction was judged on. |
| Test-suite Redis hygiene | The `/predictions` endpoint's board cache opened the real module-global Redis client during endpoint tests; the pooled connection lingered past its event loop and GC reaped it mid-suite, escalated by `filterwarnings=["error"]` into a non-deterministic failure. Fixed by closing `redis_client` in the app lifespan shutdown — correct production hygiene that also closes the connection in the right loop on each `TestClient` exit. Suite is now a deterministic 268 passed. |

### 2.6 Historical-archive data-scaling program (2026-06-28 → 07-01) — CLOSED at 2018–2023

The first program to improve the model with **more data** rather than a new
feature. DataGolf's `get-schedule` 400s for pre-2024 years, so the training set
was capped at ~6.5k–9k examples; the `historical-raw-data` archive (event-list +
per-event rounds, full SG sub-categories back to ~2013) is reachable behind an
opt-in `archive_enabled` provider flag. Extended one validated window at a time,
each gated by the standard two-regime discipline (10-event production backtest +
30-event holdout, block-bootstrap CIs, holdout make-cut Brier decisive). The
`v2_field_relative` hash (`bc91c96027e8`) was held fixed throughout — this is a
training-data change, not a feature change.

| Phase | Window | Examples | 30-event holdout make-cut Brier | Verdict |
|---|---|---|---|---|
| 1 | +2021–2023 | 9,373 → 22,917 | 0.21457 → **0.20260** (−0.012) | **PROMOTED** → `golf_v1 @ a212ed166088` |
| 2 | +2018–2020 | 22,917 → 35,804 | 0.21007 → **0.20672** (−0.0034) | **PROMOTED** → `golf_v1 @ d69cf2a7323f` (since superseded by v3, §2.7) |
| 3 | +2015–2017 | 35,804 → 48,234 | 0.20672 → **0.21034** (+0.0036 WORSE) | **REJECTED — program closed** |

- **Phases 1–2** cleared both checks: make-cut Brier and ranking improved
  (Phase 1 Spearman +0.093→+0.263, mean winner rank 46.9→34.0). Diminishing but
  real — Phase 2's make-cut gain (−0.0034) was a quarter of Phase 1's (−0.012).
- **Phase 3 (2015–2017) is the closure.** 10-event: make-cut essentially flat
  (+0.0003, ~10× smaller than prior phases) with a **ranking regression**
  (Spearman +0.291→+0.214). 30-event holdout (the decisive check that carried
  Phases 1–2): make-cut Brier **regressed +0.0036** and every market plus ranking
  got worse. Checks disagree, holdout fails → not promoted.
- **Finding:** *the archive program is complete at 2018–2023. Pre-2018 data adds
  no incremental value beyond recency-weighting attenuation* — with a 365-day
  half-life, 2015–2017 examples sit at near-zero weight at their as-of dates while
  their staler SG baselines and different course/field conditions add noise that
  slightly hurts make-cut and ordering. The monotonic decline of the make-cut gain
  (−0.012 → −0.0034 → +0.0036) is exactly the attenuation ceiling.
- **Reusable infra kept:** `archive_enabled` provider (event-list + per-event
  rounds fallback, year-correct fields around the reused-`event_id` collision);
  a **per-event rounds index** memoisation that cut field extraction from
  O(players×events) to O(events) (~60s → ~0.3s/event), which is what made
  archive-scale builds and backtests feasible; opt-in `use_historical_archive` /
  `archive_seasons` plumbing (default off → serving unchanged). Ops note: run
  archive builds/backtests one per process under `ulimit -v` (a two-arm
  single-process battery OOM-restarted the 3.8 GB container); immutable
  `event_rows` cache in Redis (~30-day TTL) makes re-runs instant once DataGolf's
  rate limit resets (cumulative session fetching can trip a multi-hour lockout).

**Archive program's final model = `golf_v1 @ d69cf2a7323f`** (v2 feature set,
archive 2018–2023, 35,804 training examples, hash `bc91c96027e8`). This was the
active model until it was superseded by the DG meta-feature promotion below
(Section 2.7), which trains on the *same* 2018–2023 archive and only adds
features.

### 2.7 External-model meta-features (`v3_dg_preds`) — PROMOTED, current active model

The endpoint audit's one viable lead, and the second major feature addition
after field-relative SG. Rather than another transform of our own SG history,
this folds in **DataGolf's own pre-tournament model probabilities** as inputs
(model-stacking): `dg_make_cut`, `dg_top_20`, `dg_top_10`, and a `has_dg_pred`
indicator, from the Pre-Tournament Predictions Archive (`baseline_history_fit`
column; `fin_text` never read; cold-start → NaN; Section 1.3). The
`v2_field_relative` hash (`bc91c96027e8`) is unchanged — v3 is a strict
superset. Same two-regime gate; baseline v2 (`d69cf2a7323f`) vs candidate v3,
identical test windows and 2018–2023 archive (the v2 arm reproduced `d69c`
exactly, confirming a clean A/B on the feature set alone):

| Check | Metric | v2 → v3 | Verdict |
|---|---|---|---|
| 10-event (gate) | make-cut skill | +0.181 → **+0.246**, CI [+0.153, +0.350] | Δ+0.065, lower CI > 0 ✓ |
| 10-event (gate) | top-20 skill | +0.088 → **+0.141**, CI [+0.115, +0.166] | Δ+0.053, lower CI > 0 ✓ |
| 10-event | ranking | Spearman +0.291 → +0.301, winner rank 33.7 → 32.2 | improved — no regression ✓ |
| 30-event holdout (decisive) | make-cut Brier | 0.20672 → **0.18308** (−0.024, ~11%) | improves ✓ |
| 30-event holdout | all markets + ranking | every market better; Spearman +0.273 → +0.321 | ✓ |

- **Both checks agree on improvement** — the largest single-change gain in the
  program's history (the holdout make-cut drop of −0.024 is ~7× Phase 1's
  archive gain). **Permutation importance** (1,147 OOS rows) confirms real
  contribution, not a lucky split: `dg_make_cut` dominates the make-cut market
  (+0.071 neg-Brier drop, larger than any SG feature); `dg_top_10`/`dg_top_20`
  lead top-20 and top-10.
- **Why it works where six prior feature cycles failed:** the DG probabilities
  are genuinely orthogonal — they carry course-fit, field composition, and
  DataGolf's talent model, none of which the SG-rolling features encode. Every
  earlier candidate (ceiling, course-fit, weather, field-shape, layoff,
  shrinkage, player random-effects, book-odds) was either a restatement of
  existing SG signal or too thin to move a CI. This is the first *external* data
  class to clear the gate.
- **Promoted + activated** `golf_v1 @ 0d2efade42ba` (trained through 2026-06-30 —
  same cutoff as `d69c`, so the only difference is the feature set; 18 features).
  Full suite 268 passed. Serving selects the feature set by the active model's
  hash, so it always matches; the DG fetch is archive-for-completed,
  live-for-current with identical shape (Section 1.3).

**ACTIVE MODEL = `golf_v1 @ 0d2efade42ba`** (v3 feature set `18a5376f33f7`, 18
features, archive 2018–2023, 35,804 training examples). Registry lineage:
136a5aca11d2 → a212ed166088 → d69cf2a7323f → **0d2efade42ba**.

---

## 3. Architecture and operations

### 3.1 Stack

- **Backend:** Python / FastAPI. Model = scikit-learn
  `HistGradientBoostingClassifier` (GBDT), one estimator per market, with
  per-market probability calibration. Served behind a stateless
  `PredictionService`.
- **Feature layer:** versioned, content-hashed feature sets. Train/serve parity
  enforced by a single `FeatureExtractor` used by training, serving, and
  backtesting. Field-relative features use the two-pass field extraction.
- **Prediction pipeline:** per-market probabilities → `coherent_outcomes`
  (nested-monotonic clamp: win ≤ top-5 ≤ … ≤ make-cut) → `normalize_field`
  (rescales each market so the field totals 1/5/10/20, fixing longshot
  over-pricing) → re-coherence. The same probabilities back the Leaderboard and
  the Betting Edge view.
- **Model registry:** content-addressed by (feature-set hash, through-date,
  hyperparameters). Note: the version id does **not** include training data or
  code, so a same-day retrain with the same feature set can overwrite a prior
  artifact under the same id — a known caveat when iterating.
- **Data:** DataGolf API is the live provider (historical rounds, schedule,
  field, projections, outright odds). Redis caching with per-method TTLs;
  immutable per-event archives cached durably. A mock provider backs the tests.
- **Frontend:** React + TypeScript (Vite). Core pages: Home, Leaderboard,
  Players, Tournaments. Betting Edge / Benchmark / Diagnostics are secondary.
- **Infra:** Docker Compose for local dev (api + postgres + redis + frontend);
  Fly.io for deploy.

### 3.2 Validation tooling

- **Rolling-origin backtest** (`app/ml/backtest.py`): trains a throwaway
  calibrated model through a cutoff, scores the N most-recent completed events
  out-of-sample. Reports per-market Brier / skill / log-loss / ECE with
  block-bootstrap 90% CIs, plus ranking metrics (Spearman, winner rank,
  winner-in-top-5/10) and a per-event breakdown. CLI: `app/cli/backtest.py`.
- **Read-only diagnostics** (`app/ml/diagnostics.py`, `app/cli/diagnose.py`):
  per-player error export, permutation importances, calibration report.
- **Bootstrap / validation** (`app/cli/bootstrap.py`): builds from the
  configured provider, trains, registers, and deep-validates a completed event
  end-to-end (labels parse, rounds dated, SG present) with ✔/⚠ remediation
  pointers.

### 3.3 Running it locally

From the repository root (Docker required):

```bash
make dev          # boot api + postgres + redis + frontend via docker compose
make ps           # show running services
make logs         # tail logs
make down         # stop (keeps volumes)
```

Backend tasks (inside the api container, or via the targets):

```bash
make test-backend                                   # full pytest suite (268 tests)
make lint-backend                                   # ruff check + format --check
make typecheck-backend                              # mypy

# Train / register on the configured provider, with end-to-end validation:
docker compose exec api uv run python -m app.cli.bootstrap

# Measure out-of-sample accuracy (with CI columns):
docker compose exec api uv run python -m app.cli.backtest --test-events 10

# Per-player error diagnostics:
docker compose exec api uv run python -m app.cli.diagnose --test-events 10
```

To run against real data, set `DATA_PROVIDER=datagolf` and `DATAGOLF_API_KEY`
in `backend/.env`, bring the stack up, then run `bootstrap`. With
`DATA_PROVIDER=mock` the same commands run fully offline.

### 3.4 Known limitations

- **Data-bound accuracy — bottleneck is information, not code.** All tractable
  orthogonal axes derivable from the *SG round history, field context, and free
  event-level data* have been tested and closed. The remaining gains come from
  new *external* data classes — the DG pre-tournament meta-features (Section 2.7)
  are the first such win and lifted every trustworthy market; further headroom
  depends on additional external signal, not more transforms of the SG history.
- **Winner market is near a practical ceiling** (≈0 skill, data-starved by ~60
  positives; driven by week-of variance the features can't see).
- **Not sportsbook-beating.** Large UI "edges" are model error, not value.
- **Registry version id** omits data/code (Section 3.1) — be deliberate about
  same-day retrains.
- **Lever A shrinkage** may be too aggressive on data-sparse stars
  (Theegala/Burns/Lowry historically under-rated) and over-rates part-time /
  Champions-Tour entrants. Tuning these priors is the most plausible remaining
  sharpness lever within the free-data ceiling, but books are efficient and
  honest framing is preferred over chasing phantom edges.

### 3.5 Conditions to reopen the research program

The program is **re-opened** by a live, validated data class (DG pre-tournament
predictions, below). It should still not reopen for another transform of
existing free SG/field data — but external-model signal is now a proven,
unexhausted axis.

**Live, unexhausted signal class (actively exploited):**

- **DataGolf pre-tournament predictions — ACTIVE data class, first external-model
  win.** Folding DataGolf's own `baseline_history_fit` probabilities in as
  meta-features cleared both gate checks with the program's largest single-change
  gain and is the current active model (Section 2.7). This axis is **not
  exhausted**: (a) DataGolf continuously improves its own model, and those gains
  **flow through automatically on the next retrain** — the feature is their live
  output, not a frozen snapshot; (b) other archive columns (`top_5`, `top_3`,
  `top_30`, `first_round_leader`) and other providers' models are untested
  meta-feature candidates. Any of these is a valid next experiment under the
  standard two-regime gate.

**Recently exploited or re-validated (now closed, do not retry):**

- **Historical-archive training data — EXPLOITED, closed at 2018–2023.** The
  DataGolf `historical-raw-data` archive (a genuine new data class: pre-2024
  events `get-schedule` can't reach) multiplied the training set ~6.5×
  (6,519 → 35,804). Validated one window at a time: +2021–2023 and +2018–2020
  both cleared the two-regime gate and were promoted; +2015–2017 failed
  (make-cut holdout Brier regressed, ranking dropped) — recency weighting
  attenuates pre-2018 to near-zero weight. Full detail in Section 2.6.
- **Recency half-life — RE-VALIDATED at 365 days.** Re-tested at the new 35.8k
  scale (180 / 545 / 730 vs 365); none cleared the tighter gate without a
  make-cut or ranking regression. 365d is the Pareto sweet spot. Closed.

**Qualifying triggers that would still reopen the program:**

- **Real course attributes at full schedule coverage** (yardage, course type,
  not just the ~33 curated venues). Course identity and par are already in the
  DataGolf rounds payload at full coverage; only yardage and type need an
  external table. With full coverage, course-fit is worth retrying.
- **Leakage-safe pre-event conditions** — paid archived forecast products
  (Open-Meteo Professional, Visual Crossing add-on) that allow wind × player
  or wind × course *interactions* (an event-level scalar already failed; only
  interactions can reorder within-field).
- **Betting-market priors as a feature** — historical *opening* odds (not
  closing) usable as a training feature with live odds at serve time. This is
  the most direct route to closing the gap to the book, but requires historical
  odds availability and careful parity handling.

The prior "final model" conclusion no longer holds: the DG meta-feature
promotion reopened the program along the external-model axis. The active model
is the current validated baseline, not a terminal one.

---

## 4. What this project demonstrates methodologically

The technical result is a model at its data-bound ceiling. The more
transferable result is the **discipline that established the ceiling as a
finding rather than an assumption**.

### 4.1 Two-regime + holdout validation

No feature is promoted on a single backtest split. Every candidate runs:

1. **10-event production-regime backtest** — trains on the real deployment scale
   (≈7,500 examples before the historical archive; ≈35k after, from 2018–2023).
   The primary gate (≥ +0.010 Brier skill on make-cut or top-20, no ranking
   regression).
2. **85-event cross-check** — a deliberately data-starved regime (≈39 training
   events) that surfaces small-data artifacts.
3. **Production-scale holdout** — independent of the backtest split; the
   tiebreaker when the two backtests disagree (make-cut holdout Brier must
   improve).

This discipline repeatedly caught split variance: `min_samples_leaf=80` showed
a *false positive* in the 85-event regime that reversed at scale (promoted on
10-event + holdout agreement); layoff and the player random-effects prior each
showed a *false positive* in the 10-event regime that the holdout overturned
(both rejected). The lesson — recorded and re-applied — is that the regime
must match the decision: production-scale for regularization, holdout for
tiebreaks.

### 4.2 Evidence before engineering

Features are not built on intuition. A read-only test or diagnostic gates the
build. Experiment B is the cleanest example: before any course feature was
written, a read-only residual-structure test asked "do finishing residuals
cluster by course beyond the known field-strength bias?" The answer (no —
they're a player effect) closed the entire course program without writing a
course feature. The ceiling and weather pilots followed the same order:
feasibility / read-only analysis first, implementation only if it cleared.

### 4.3 Honest closure of negative results

Nine ceiling-test directions failed and all nine were reverted cleanly, with
the mechanism recorded each time — not left half-implemented or rationalized.
Negative results were treated as the deliverable: each closure narrowed the
hypothesis space and built the cumulative case that the ceiling is real. The
project explicitly prefers "if no meaningful improvement, revert" over
iterating on a dead lead.

A specific instance of honesty against self-interest: when the player
random-effects prior cleared the 10-event gate, the 85-event +0.000 result was
recorded as *structurally uninformative* (the feature was constant-zero in that
regime's training) rather than claimed as either support or refutation — and
the decision rested on the holdout, which was negative.

### 4.4 Block-bootstrap CIs as the promotion rule

The recurring failure mode was a favorable point estimate on one split that
did not survive. The fix is statistical, not procedural: a block-bootstrap CI
(resampling whole events, the correct correlated unit) on each market's skill,
with the promotion rule "lower CI bound > 0." Applied to the active model, the
CIs are themselves the cleanest statement of scope: make-cut [+0.153, +0.350],
top-20 [+0.115, +0.166], and top-10 [+0.035, +0.109] have lower bounds above
zero (genuine skill), while win and top-5 straddle zero. A +0.010–0.013
single-split gain — the size that drove the rejected candidates — sits
comfortably inside that noise band, which is exactly why it is no longer
promotable. The DG meta-feature win cleared this bar decisively (make-cut and
top-20 lower bounds moved to +0.153 and +0.115).

### 4.5 The chain of experiments that built confidence in the ceiling

The ceiling finding is credible because it is the convergent result of many
independent attempts, not one analysis:

1. Field-relative SG worked enormously → established that *orthogonal,
   event-level* information is the lever.
2. Repeated player-history transforms (Lever B, ceiling, recency, random-
   effects prior) all failed the incremental gate → the player-history
   subspace is **saturated** (~2 latent dimensions).
3. Course-fit failed, then Experiment B proved the residual structure is a
   **player effect, not a venue effect** → course information carries no
   orthogonal ranking signal.
4. Field-shape features failed and did not move the target residual → the
   weak-field bias is a player/data-sparsity effect, not a functional-form gap.
5. A leakage-safe weather pilot failed flat-to-worse → event-level scalars
   can't reorder within-field.
6. Empirical-Bayes shrinkage added nothing the GBDT didn't already encode.
7. The validation harness itself was hardened (block-bootstrap CIs) so the
   ceiling claim rests on interval estimates, not point estimates.

Each result independently pointed at the same boundary: under the current
free-data constraint, the residual that separates the contender pack is
event-level variance (form, draw, conditions) not recoverable from 730 days of
SG round history. That convergence — across the feature space, the field-
context space, and the player-uncertainty space — is what makes the ceiling a
finding worth recording rather than a place the work happened to stop.

---

*Snapshot date: 2026-07-02. Active model: `golf_v1 @ 0d2efade42ba` (v3
feature set `v3_dg_preds`, 18 features, historical archive 2018–2023, 35,804
training examples). The SG-feature / hyperparameter research program is complete
(Sections 2.2–2.4) and the historical-archive data-scaling program is complete
at 2018–2023 (Section 2.6); the external-model meta-feature axis is newly
**open** — DataGolf pre-tournament predictions were promoted as the current
active model (Section 2.7) and that data class is unexhausted (Section 3.5).*
