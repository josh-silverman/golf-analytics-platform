# PGA Analytics — State of the Project

A consolidated snapshot of the predictive model, the research program that
validated its performance ceiling, the architecture, and the methodology used
to reach these conclusions. This is a **reference document**, not a roadmap:
it records where the project stands as of **2026-06-23** and the evidence
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
| Active version | `136a5aca11d2` |
| Feature set | `v2_field_relative` (hash `bc91c96027e8…`) |
| Feature count | 14 |
| Estimator | scikit-learn `HistGradientBoostingClassifier`, one per market |
| Markets | win, top-5, top-10, top-20, make-cut |
| Calibration | per-market: sigmoid (win, top-5) + isotonic (top-10, top-20, make-cut) |
| Trained through | 2026-06-16 |
| Training examples | 6,519 (+ 2,173 held out for calibration) |
| Training span | 3 PGA seasons, 365-day recency weighting |
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

### 1.3 Feature set (`v2_field_relative`, 14 features)

Every feature is derived from a player's strokes-gained (SG) round history.
There is no player identity, no course attribute, no weather, and no market
signal in the model — those were all tested and did not clear the gate.

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

Field-relative features are computed by a **two-pass field extraction**
(`FeatureExtractor.extract_field`): compute each player's absolute features →
average across the field → recompute as margins vs. the field mean. The same
code path runs in training, serving, and backtesting — this is the
train/serve-parity invariant the whole feature layer exists to protect.

### 1.4 Validated performance ceiling (per market)

Out-of-sample, from the rolling-origin backtest of the active model
(`136a5aca11d2`), 10 most-recent completed events, 1,223 predictions, trained
through 2026-04-22. The 90% confidence interval is from the block-bootstrap
infrastructure (Section 3.2), resampling whole events with replacement.

| Market | Base rate | Brier | Brier skill vs base rate | 90% CI (block-bootstrap) | Verdict |
|---|---|---|---|---|---|
| win | 0.9% | 0.0089 | +0.003 | **[−0.001, +0.007]** | straddles 0 — no edge |
| top-5 | 5.1% | 0.0477 | +0.008 | **[−0.054, +0.062]** | straddles 0 — noisy |
| top-10 | 10.5% | 0.0918 | +0.021 | **[−0.011, +0.046]** | straddles 0 |
| top-20 | 21.3% | 0.1568 | +0.063 | **[+0.029, +0.093]** | lower CI > 0 — genuine skill |
| make-cut | 58.5% | 0.2065 | +0.149 | **[+0.078, +0.220]** | lower CI > 0 — genuine skill |

Held-out calibrated Brier from the registered artifact (independent of the
backtest split): win 0.00941, top-5 0.04925, top-10 0.09122, top-20 0.15476,
make-cut 0.19956.

**Brier skill score** = `1 − model_brier / base_rate_brier`. Positive means the
model beats predicting the field-average rate for everyone. It does **not**
mean beating a sportsbook — that is a far higher bar the model does not clear
(Section 1.5).

### 1.5 Honest scope — which markets to trust

- **make-cut and top-20 are trustworthy.** Their lower CI bounds are clearly
  above zero (+0.078 and +0.029). These markets carry real, reproducible skill
  over the naive baseline and are where the model's analytic value lives.
- **win, top-5, top-10 are intentionally coarse.** Their skill CIs straddle
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

- **Data-bound accuracy ceiling.** The model is at its performance ceiling
  under the current free-data constraint. The bottleneck is information, not
  code: all tractable orthogonal axes derivable from the SG round history,
  field context, and free event-level data have been tested and closed.
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

The program is closed **pending a new data class**, not closed permanently. It
should reopen only when genuinely orthogonal information becomes available —
not for another transform of existing free SG/field data. Qualifying triggers:

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

Until one of these lands, the validated conclusion stands: the active model is
the final model.

---

## 4. What this project demonstrates methodologically

The technical result is a model at its data-bound ceiling. The more
transferable result is the **discipline that established the ceiling as a
finding rather than an assumption**.

### 4.1 Two-regime + holdout validation

No feature is promoted on a single backtest split. Every candidate runs:

1. **10-event production-regime backtest** — trains on ≈7,500 examples, the
   real deployment scale. The primary gate (≥ +0.010 Brier skill on make-cut or
   top-20, no ranking regression).
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
CIs are themselves the cleanest statement of scope: make-cut [+0.078, +0.220]
and top-20 [+0.029, +0.093] have lower bounds above zero (genuine skill), while
win, top-5, and top-10 straddle zero. A +0.010–0.013 single-split gain — the
size that drove the rejected candidates — sits comfortably inside that noise
band, which is exactly why it is no longer promotable.

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

*Snapshot date: 2026-06-23. Active model: `golf_v1 @ 136a5aca11d2`. The research
program is complete; reopen only on a new data class (Section 3.5).*
