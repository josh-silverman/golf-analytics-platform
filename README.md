# Pinpoint — PGA Tour Pre-Tournament Prediction Model

An engineering case study in building a calibrated, leakage-safe machine-learning
model for PGA Tour outcome prediction on top of the [DataGolf](https://datagolf.com)
API — and, just as importantly, in **rigorously establishing where its predictive
ceiling is** and refusing to ship features that don't beat it out-of-sample.

This README is the project's definitive technical history. It documents the full
evolution — every major model version, the feature-engineering wins, the long list
of experiments that **failed and were reverted**, the validation methodology and how
it hardened over time, and the honest conclusions the work produced. The negative
results are treated as first-class deliverables: they are what turned "the model is
probably near its ceiling" from an assumption into a measured finding.

> **On sourcing.** Everything below is reconstructed from the git history, the
> consolidated research record in [`docs/project-summary.md`](docs/project-summary.md),
> the validation artifacts, and the code. Where a specific number could not be
> verified from a committed artifact, that is stated explicitly rather than invented.
> Chronology is inferred only where commits, docs, or validation logs strongly
> support it.

---

## Table of contents

- [The objective](#the-objective)
- [What the system is today](#what-the-system-is-today)
- [Chronological timeline](#chronological-timeline)
- [Model versions in detail](#model-versions-in-detail)
- [The ceiling-finding program](#the-ceiling-finding-program-negative-results-as-the-deliverable)
- [Key discoveries](#key-discoveries)
- [Validation methodology and how it evolved](#validation-methodology-and-how-it-evolved)
- [Current architecture](#current-architecture)
- [Limitations and open research questions](#limitations-and-open-research-questions)
- [Roadmap — Path A](#roadmap--path-a)
- [Repository layout](#repository-layout)
- [Running it](#running-it)
- [License](#license)

---

## The objective

Build a **pre-tournament** predictive model for PGA Tour events that, for each player
in a field, outputs calibrated probabilities across five nested markets — **win,
top-5, top-10, top-20, and make-cut** — using [DataGolf](https://datagolf.com) as the
data source (historical round-level strokes-gained, schedules, fields, and DataGolf's
own pre-tournament projections).

Three principles governed the work from the start:

1. **Sharp, honestly-scoped accuracy** over impressive-looking dashboards. A market is
   only claimed as "skilled" if its out-of-sample Brier-skill confidence interval
   clears zero.
2. **Leakage safety as an invariant**, not an afterthought — every feature is computed
   as-of the prediction date, and training and serving run the *same* code path.
3. **Discard what doesn't work.** A feature ships only if it beats the incumbent
   out-of-sample under a pre-registered gate; otherwise it is reverted cleanly and the
   negative result is recorded with its evidence.

---

## What the system is today

- **Active model:** `golf_v1 @ 0d2efade42ba` — five independent
  `HistGradientBoostingClassifier` heads (one per market) on an 18-feature set
  (`v3_dg_preds`), each with its own probability calibration, trained on ~35,800
  examples spanning the 2018–2023 historical archive plus 2024+ live events with
  365-day recency weighting.
- **What it does well:** make-cut and top-20 carry genuine, reproducible
  out-of-sample skill (lower CI bounds clearly above zero); top-10 is genuine under
  v3; predictions are coherent (win ≤ top-5 ≤ … ≤ make-cut) and field-normalized by
  construction.
- **What it honestly does not do:** beat a sharp sportsbook on any market, or predict
  winners with meaningful skill (that market is data-starved and dominated by
  week-of variance).
- **Test suite:** 275 passing tests (backend), deterministic.

Full identity and hyperparameters are in
[`docs/project-summary.md` §1](docs/project-summary.md).

---

## Chronological timeline

Dates are from the git history. The project moved through a scaffold-then-model
sequence, then a feature-engineering phase, then a long ceiling-finding program.

| Date (2026) | Milestone | Significance |
|---|---|---|
| Jun 2–8 | **Scaffold → full platform (Phases 0–5).** FastAPI + React + Postgres + Redis, `DataProvider` interface with a deterministic mock provider, feature/registry/training/calibration layers, Monte-Carlo simulation, betting-edge UI, and the real DataGolf integration. | The engineering substrate: train→register→predict loop, contract-tested provider swap, train/serve-parity feature extractor. |
| Jun 15 | **`golf_v1 @ 136a5aca11d2`** — first registered model with field-relative SG (`v2`), per-market calibration, `min_samples_leaf=80`. | First real model. Field-relative context was the single biggest accuracy win of the whole project (see [v2](#v2--field-relative-strokes-gained-the-biggest-win)). |
| Jun 18 | Product consolidation (leaderboard hub, model track-record, block-bootstrap groundwork), brand → "Pinpoint". | Shift from "many pages" to a focused product. |
| Jun 23 | **Block-bootstrap 90% CIs added to the backtest harness.** Promotion rule becomes: point estimate ≥ threshold **and** lower CI bound > 0. | The methodological turning point — this is what started catching single-split false positives. |
| Jun 28 – Jul 1 | **Historical-archive data-scaling program.** Training set grows ~6.5k → 35.8k examples by adding the 2018–2023 archive, validated one window at a time. Closed at 2018–2023 (pre-2018 rejected). | First improvement from *more data* rather than a new feature. `golf_v1 @ d69cf2a7323f`. |
| Jul 2 | **`v3_dg_preds` promoted → `golf_v1 @ 0d2efade42ba`** (current active). Folds DataGolf's own pre-tournament probabilities in as meta-features. | Largest single-change gain in the program's history — and the only *external* data class to clear the gate. |
| Jul 9–10 | **Rank-native research track** + final feature-space audit (blow-up rate, course-fit interaction, tee-time wave). | All closed. Confirmed the SG-adjacent feature space is exhausted; produced the DataGolf-recovery finding below. |

---

## Model versions in detail

### v1 — baseline SG skill ratings

- **Why built:** the minimum viable model — close the train→register→predict loop and
  establish a floor.
- **What it was:** six features, all derived from a player's own strokes-gained
  history in isolation — five time-decayed SG category ratings (off-the-tee, approach,
  around-the-green, putting, total) plus a `form_index` (recent vs. baseline SG).
- **Validation / outcome:** functional but weak. Its documented pathology was that it
  **could not separate winners from the pack** — predicting outcomes in isolation,
  with no notion of the field a player actually faces. *(Exact v1 backtest numbers are
  not preserved in the consolidated research record; the qualitative weakness is what
  is documented and what motivated v2.)*
- **Lesson:** a model that describes each player in a vacuum can't rank a field.

### v2 — field-relative strokes-gained (the biggest win)

- **Why built:** to fix v1's core pathology. Win and top-N probability are inherently
  *relative* quantities — a +1.0 SG player is a heavy favorite in a weak field and a
  coin-flip in a major.
- **What changed:** added, on top of the v1 ratings, five **field-relative** SG
  margins (player skill minus the field mean in each category), `field_strength` (mean
  field SG), `round_count` (sample size behind the estimate), and `score_volatility`.
  Also added a **low-data shrinkage prior** (thin histories regress toward a
  below-average prior worth ~5 pseudo-rounds, killing phantom edges) and **365-day
  recency weighting**. Feature set `v2_field_relative`, hash `bc91c96027e8`, 14
  features.
- **Validation / outcome:** ✅ **the single biggest improvement ever made.** It fixed
  the winner-separation pathology directly. On the 2018–2023 archive
  (`golf_v1 @ d69cf2a7323f`): make-cut skill **+0.181**, top-20 **+0.088**, ranking
  Spearman **+0.291**.
- **Lesson:** *orthogonal, event-level information* is what helps. This lesson
  correctly predicted which later features would work (external, orthogonal) and which
  would fail (restatements of existing SG signal).

**Historical-archive scaling (a v2 training-data change, not a feature change).**
DataGolf's `get-schedule` can't reach pre-2024 events, so the training set was capped
at ~6.5–9k examples. An opt-in archive path (`historical-raw-data`) lifted that to
35.8k by adding 2018–2023, validated one window at a time on the 30-event holdout
make-cut Brier:

| Window added | Examples | Holdout make-cut Brier | Verdict |
|---|---|---|---|
| +2021–2023 | 9.4k → 22.9k | 0.21457 → 0.20260 (−0.012) | **promoted** |
| +2018–2020 | 22.9k → 35.8k | 0.21007 → 0.20672 (−0.0034) | **promoted** |
| +2015–2017 | 35.8k → 48.2k | 0.20672 → 0.21034 (+0.0036 **worse**) | **rejected — closed** |

The monotonic decay of the gain (−0.012 → −0.0034 → +0.0036) *is* the recency-weighting
attenuation ceiling: with a 365-day half-life, pre-2018 examples sit at near-zero
weight while their staler baselines add noise. A per-event rounds-index memoization cut
field extraction from O(players×events) to O(events) (~60s → ~0.3s/event), which is
what made archive-scale training and backtesting feasible.

### v3 — DataGolf meta-features (current active model)

- **Why built:** after nine feature cycles failed to add orthogonal signal (see
  below), the one remaining untried axis was **external-model signal** — using another
  model's output as an input (model stacking) rather than another transform of our own
  SG history.
- **What changed:** added four features from DataGolf's Pre-Tournament Predictions
  Archive (`baseline_history_fit` column only): `dg_make_cut`, `dg_top_20`,
  `dg_top_10`, and a `has_dg_pred` cold-start indicator. `v3_dg_preds`, 18 features. The
  `v2` hash is unchanged — v3 is a strict superset. Cold-start (no archive entry, or a
  player missing from an event) yields `NaN`, which the GBDT routes natively; the
  post-event `fin_text` DataGolf staples on is **never read** (dropped with an explicit
  assertion) so there's no label leakage.
- **Validation / outcome:** ✅ **the largest single-change gain in the program.** Both
  gate checks agreed:

  | Check | Metric | v2 → v3 |
  |---|---|---|
  | 10-event gate | make-cut skill | +0.181 → **+0.246** (CI [+0.153, +0.350]) |
  | 10-event gate | top-20 skill | +0.088 → **+0.141** (CI [+0.115, +0.166]) |
  | 30-event holdout (decisive) | make-cut Brier | 0.20672 → **0.18308** (−0.024, ~11%) |
  | 10-event | ranking | Spearman +0.291 → +0.301, no regression |

  Permutation importance on 1,147 out-of-sample rows confirmed real contribution
  (`dg_make_cut` outweighs any single SG feature on the make-cut market), not a lucky
  split.
- **Why it worked where six feature cycles failed:** the DG probabilities are
  genuinely orthogonal — they encode course-fit, field composition, and DataGolf's
  talent model, none of which the SG-rolling features carry.
- **Important caveat (see [Key discoveries](#key-discoveries)):** a later head-to-head
  investigation found that on DataGolf-**covered** players, v3 largely *recovers*
  DataGolf's own signal rather than adding much orthogonal predictive value on top of
  it. v3 is still the right production choice — but for reasons (cold-start fallback,
  coherent calibrated multi-market output) that are more nuanced than "the ML layer
  beats DataGolf."

**Registry lineage:** `136a5aca11d2` (v2) → `a212ed166088` (+2021–2023) →
`d69cf2a7323f` (+2018–2020) → **`0d2efade42ba`** (v3, active).

---

## The ceiling-finding program (negative results as the deliverable)

The core research thesis is that **the model sits at its information ceiling under the
current data**, and the evidence for that is a long list of plausible ideas that were
tested and *closed*. Each was tested read-only first, gated on the rolling backtest,
and reverted cleanly when it failed — none changed the active model.

**Shipped (validated) improvements:** field-relative SG (v2), low-data shrinkage
prior, recency weighting, `min_samples_leaf` 20→80 (the *only* hyperparameter tuning
win of the entire program), and the DG meta-features (v3).

**Closed directions (all reverted):**

| Direction | Outcome |
|---|---|
| Longer history window | ❌ Stale rounds dragged current players down; ranking collapsed. |
| Ceiling / upside feature | ❌ Standalone correlation but ~zero incremental value; moved 28% of predictions as symmetric noise. |
| Course-fit (early, length × driver over ~33 hardcoded venues) | ❌ Thin low-signal split that hurt ranking. |
| Course residual structure (read-only) | ❌ Finishing residuals cluster by venue only via the known field-strength bias; residual is a **player** main effect, not a venue effect. Course program closed. |
| Weather (event-level wind scalar) | ❌ Every market flat-to-worse; an event-level scalar can't reorder *within* a field. |
| Field-shape (dispersion / depth / percentile) | ❌ Failed the gate; the weak-field residual is a player effect, not a functional-form gap. |
| Layoff / staleness | ❌ Inconclusive — one favorable split, null and worse on the others. |
| Empirical-Bayes shrinkage | ❌ Redundant; GBDT already captures n-weighted shrinkage via `sg_total_rating` + `round_count`. |
| Player random-effects prior | ❌ Cleared the 10-event gate but regressed the holdout — the exact split-variance failure the CI rule exists to catch. |

**A second, deeper research track (Jul 9–10)** stress-tested the ceiling from two more
angles and confirmed it:

- **Is the model "just DataGolf with extra steps"?** A DG-standalone head-to-head plus
  paired-delta bootstrap found that on covered players, v3 ≈ DG-standalone on
  make-cut/top-20/top-10 and *worse* on win/top-5, with the SG features carrying only
  **~0.0004 Brier of orthogonal signal**. (See [Key discoveries](#key-discoveries).)
- **A rank-native architecture** (a strength-and-variance simulation replacing the five
  independent classifiers) was designed, an evaluation harness built and validated
  against the DG-standalone baseline, and six experiments run (single-feature μ →
  multi-feature μ → ranking-aware μ). All converged on the same wall: the SG features
  have a hard ordering ceiling (~+0.30 Spearman) that never reaches DataGolf on the
  ranking markets. The pre-registered kill criterion was invoked; the model is shelved
  as a documented research result.
- **Three final feature candidates** — a double-bogey-or-worse **blow-up rate**, a
  **course-length × driver-distance interaction** (built on a real external
  69-course yardage table), and a **Round-1 tee-time wave** feature — were each
  implemented and run through the full two-regime battery. All three closed. The wave
  case is the most instructive: a read-only analysis found a **real** ~0.25-stroke
  AM-vs-PM scoring effect (t≈4.5 across 278 events), but because the standard R1/R2
  draw is mirrored (every player gets one AM and one PM round before the cut), the
  effect **nets out** over every scoring window that matters — a genuine effect that
  is structurally un-exploitable as a pre-event feature.

---

## Key discoveries

1. **Field-relative context is everything.** The largest accuracy jump came not from a
   better estimator but from expressing skill *relative to the field faced*. Ranking a
   field is an inherently relative problem.

2. **The model is data-bound, not code-bound.** Every tractable axis derivable from the
   SG round history, field context, and free event-level data has been tested and
   closed. The bottleneck is information, not modeling.

3. **Stacking DataGolf largely *recovers* DataGolf, rather than beating it.** This is
   the most important and most honest finding. v3's gains come almost entirely from the
   DG meta-features, and a direct head-to-head shows that on DataGolf-covered players,
   the model's output is essentially DataGolf's own signal re-expressed — it does not
   add measurable orthogonal predictive value on the covered set, and is *worse* than
   DataGolf on the win/top-5 markets. The SG features contribute only ~0.0004 Brier of
   independent signal there. The genuine value the ML layer adds is therefore narrower
   and more defensible than a naive "our model is accurate" claim: (a) a **cold-start
   fallback** (SG-only prediction for players/events DataGolf doesn't cover), and (b) a
   **coherent, field-normalized, calibrated multi-market product** built around the
   external signal.

4. **A real effect is not always an exploitable feature.** The tee-time wave effect is
   real and statistically robust, yet washes out over the mirrored two-wave draw. Signal
   detection and feature value are different questions.

5. **Winner prediction has a low practical ceiling.** ~0 skill, driven by week-of
   variance (form, draw, conditions) the player-history features can't see, and
   data-starved (~60 winners in the training set).

6. **Document closures with their evidence, not just a verdict.** An early
   `teetime`/`start_hole` closure had been made by *inference* ("a weather proxy, no
   value") with no recorded test — and a later direct test found it was half-wrong (a
   real AM/PM effect existed; the start-hole half was correctly closed). An undocumented
   "closed by reasoning" can't be correctly re-examined when a mechanism surfaces later.
   This is now a standing methodological rule (see
   [`docs/project-summary.md` §4.3](docs/project-summary.md)).

---

## Validation methodology and how it evolved

The methodology hardened in direct response to failures — each tightening was added
because a looser rule had let a false positive through.

1. **Single rolling-origin backtest (start).** Train a throwaway calibrated model
   through a cutoff; score the N most-recent completed events out-of-sample on
   per-market Brier / skill / log-loss / ECE plus ranking metrics.
2. **Two-regime + holdout (added after split-variance burned validation runs).** Every
   candidate runs a **10-event production-regime** backtest (real deployment scale), a
   larger **cross-check** regime (data-starved, surfaces small-data artifacts), and a
   **production-scale holdout** that acts as the tiebreaker when the two disagree. The
   recurring lesson — recorded and re-applied — is that *the regime must match the
   decision*: production-scale for regularization, holdout for tiebreaks.
3. **Block-bootstrap 90% confidence intervals (Jun 23).** Resample *whole events* (the
   correct correlated unit — predictions within an event are not independent) to put a
   CI on each market's Brier skill. The promotion rule became **point estimate ≥
   threshold AND lower CI bound > 0**. This directly caught the single-split false
   positives that had cost three validation runs each in the layoff and
   player-random-effects cycles.
4. **Paired-delta bootstrap (Jul).** For head-to-head comparisons (model A vs. model B
   on identical rows), a paired-delta bootstrap on the same resampled events gives a CI
   on the *difference*, which is far more sensitive than comparing two overlapping
   marginal CIs.
5. **Pre-registered gates + clean reverts.** A gate is written down *before* the run;
   if it isn't met, the feature code (and any scaffolding, e.g. the external course
   table) is reverted, the feature-set hash is confirmed unchanged, the suite is run
   green, and the negative result is recorded with its numbers.

The leakage invariant runs underneath all of it: features are computed as-of the
prediction date over a fixed 730-day window, and training, serving, and backtesting all
call the **same** `FeatureExtractor` — the parity guarantee the feature layer exists to
protect.

---

## Current architecture

```
                       DataGolf API  (rounds · schedule · field · projections · odds)
                              │
                     ┌────────▼────────┐   Redis: immutable per-event archives (30d TTL)
                     │  DataGolfProvider│   + per-method TTL caches
                     │  (or MockProvider)│  ← contract-tested, drop-in swap
                     └────────┬────────┘
                              │
                   ┌──────────▼───────────┐
                   │  FeatureExtractor     │  one code path for train / serve / backtest
                   │  (train/serve parity) │  two-pass field-relative extraction
                   └──────────┬───────────┘  content-hashed, versioned feature sets
                              │  18-feature v3 vectors (leakage-safe, as-of)
                   ┌──────────▼───────────┐
                   │  5 × HistGBClassifier │  one head per market + per-market calibration
                   └──────────┬───────────┘  (sigmoid: win/top-5 · isotonic: top-10/20/cut)
                              │
          coherent_outcomes (win ≤ top-5 ≤ … ≤ make-cut)  →  normalize_field (Σ = 1/5/10/20)
                              │
        ┌─────────────────────┼─────────────────────┐
   FastAPI  /predictions   Rolling-origin backtest    Model registry
   Leaderboard · Player     + block-bootstrap CIs      (content-addressed by
   · Betting-edge (React)    + paired-delta harness      feature-hash / cutoff / hparams)
```

**What the architecture does well:**

- **Train/serve parity by construction** — a single feature extractor means a feature
  can't behave differently in training and production.
- **Content-hashed feature sets + a model registry** keyed by (feature-set hash,
  through-date, hyperparameters), so "is this prediction stale?" is a column comparison.
- **Coherent, field-normalized probabilities** — the nested markets are monotone by
  construction and each market sums correctly across the field.
- **A validation harness that is itself the product** — the rolling-origin backtest
  with block-bootstrap CIs is what every promotion decision rests on.
- **Honest product framing** — the UI leads with make-cut / top-20 / finish
  distribution; the betting view is explicitly a model-vs-market *research* lens, not a
  +EV claim.

**Stack:** Python 3.12 · FastAPI · scikit-learn `HistGradientBoostingClassifier` ·
Redis · PostgreSQL · React 19 + TypeScript (Vite). A deliberate constraint — no
OpenMP-based libraries (XGBoost/LightGBM) — keeps the dependency surface small and
shaped several modeling choices. Docker Compose for local dev; Fly.io as the deploy
target (a `fly.toml` exists; the project is not necessarily deployed).

---

## Limitations and open research questions

- **Data-bound accuracy.** The SG-adjacent feature space is exhausted. Further gains
  require a genuinely new *external* data class, not more transforms of the SG history.
- **The v3 value question (open).** Since v3 largely recovers DataGolf's signal on
  covered players, an honest open question is how much predictive value the ML layer
  adds *beyond* cold-start coverage and calibration. This is the motivation for Path A.
- **Winner market** is near its practical ceiling and data-starved.
- **Not sportsbook-beating** on any market — verified live against real book odds.
  Large UI "edges" are model error, not value.
- **Single-vendor dependency.** The one external win (DG meta-features) makes the model
  reliant on DataGolf's continued output and schema; there are fixtures but not full
  contract tests against live schema drift.
- **Registry version id** omits training data and code — a same-day retrain with the
  same feature set can overwrite a prior artifact under the same id. Iterate
  deliberately.
- **Not re-runnable as committed artifacts.** Much of the experiment record lives as
  prose plus one-off scripts and depends on mutable upstream data; a second engineer
  could not reproduce every promotion decision from the repo alone. (Flagged in the
  project's own [technical due-diligence review](docs/technical-due-diligence.md).)

---

## Roadmap — Path A

The research program concluded that the pre-tournament, SG-adjacent feature space is
exhausted. The forward path is therefore not "more features" but a cleaner serving
architecture plus product differentiation:

- **Path A serving.** DataGolf-direct for covered players (since that's where the
  signal demonstrably is), with the **v2 SG-only model as the cold-start fallback** for
  players/events DataGolf doesn't cover. This makes the division of labor explicit and
  honest.
- **Product differentiation on top of the signal** — the leaderboard, finish-distribution
  and player-trend views, the model-vs-market research lens, and an accumulating
  *out-of-sample* track record (persisting each event's pre-event board at prediction
  time so the on-site stat becomes a genuine forward record rather than an in-sample
  one).
- **Reopen the modeling program only on a substantially new external data class** — not
  another incremental transform. The bar is deliberately high to avoid the
  evaluation-capital exhaustion the due-diligence review flagged.

---

## Repository layout

```
backend/
  app/
    features/        versioned, content-hashed feature sets + primitives
    ml/              trainer, calibration, rolling-origin backtest, rank_v1 research harness
    providers/       DataProvider interface · DataGolfProvider · MockDataProvider (contract-tested)
    services/        FeatureExtractor (train/serve parity), PredictionService, catalog
    api/ · db/ · cache/   FastAPI layer, SQLAlchemy models, Redis caching
  tests/             275 passing tests
frontend/            React 19 + TypeScript (Vite) — leaderboard, player, betting-edge, diagnostics
docs/
  project-summary.md         the consolidated research record (primary source for this README)
  project-brief.md           how to judge proposed work against settled results
  technical-due-diligence.md independent review of the system's risks and gaps
  rank-native-model-design.md the shelved rank-native architecture design
  architecture/              the original 12-section system-design pass
```

---

## Running it

```bash
make dev            # boot api + postgres + redis + frontend via docker compose
make test-backend   # full pytest suite (275 tests)
make lint-backend   # ruff check + format --check
make typecheck-backend

# Train / register on the configured provider, with end-to-end validation:
docker compose exec api uv run python -m app.cli.bootstrap

# Measure out-of-sample accuracy (with block-bootstrap CI columns):
docker compose exec api uv run python -m app.cli.backtest --test-events 10

# Per-player error diagnostics + permutation importances:
docker compose exec api uv run python -m app.cli.diagnose --test-events 10
```

Set `DATA_PROVIDER=datagolf` and `DATAGOLF_API_KEY` in `backend/.env` to run against
real data; with `DATA_PROVIDER=mock` the same commands run fully offline against the
deterministic mock provider.

---

## License

MIT — see [LICENSE](LICENSE). Data provided by [DataGolf](https://datagolf.com),
acknowledged as the source of all round-level, schedule, field, and pre-tournament
prediction data used by the model.
