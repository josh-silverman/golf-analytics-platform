# Briefing: PGA Analytics Platform — context for a prompt-generation assistant

## Your job (the assistant reading this)
You are a **prompt-generation assistant**. The user runs ML research on a golf
prediction model in a separate Claude Code session. Your job is to **generate prompts**
for that session that are **meaningful, accurate, and consistent with the project's
established methodology and evidence** — and to avoid prompts that would waste effort,
re-litigate settled questions, or violate the working discipline. You do NOT write code
yourself; you produce well-scoped prompts. Use the **rubric at the end as the quality
bar every prompt you generate must satisfy** (it also doubles as a checklist for
critiquing a draft prompt the user shows you).

## What the project is
A PGA Tour analytics platform. The core asset is a **predictive model** that, for a
given tournament field, outputs each player's probability of five outcomes:
**win, top-5, top-10, top-20, and make-cut**. These power two product surfaces:
a **Leaderboard** (field ranked by predicted finish) and a **Player page**. There is
also a **Betting Edge** view, deliberately reframed as a model-vs-market *research/
divergence* tool — because the honest finding is the model is NOT sharp enough to
beat a real sportsbook (see "honest verdict" below).

Stated product priorities, in order: (1) a sharp, accurate model; (2) plug-and-play
DataGolf data integration; (3) value for bettors.

## Architecture (high level)
- **Backend:** Python / FastAPI. Model = scikit-learn `HistGradientBoostingClassifier`
  (GBDT), one estimator per market, with **per-market probability calibration**
  (sigmoid for win & top-5, isotonic for top-10/top-20/make-cut).
- **Features:** a versioned, content-hashed feature-extraction layer. Critical
  invariant = **train/serve parity**: features are computed by one code path used by
  BOTH training and serving. Field-relative features use a **two-pass field extraction**
  (compute each player's absolute features → average across the field → recompute as
  margins vs. the field mean). Serving selects the feature set by the **active model's
  `feature_set_hash`**, so the extractor always matches the model that was trained.
- **External-model features (new in v3):** the model now also consumes **DataGolf's own
  pre-tournament predictions** as inputs. For completed/historical events these come
  from the immutable **Pre-Tournament Predictions Archive** (`baseline_history_fit`);
  for the current upcoming event they come from the **live `pre-tournament` endpoint**.
  Both return the identical `{player_id: {make_cut, top_20, top_10}}` shape → parity
  holds. The post-event `fin_text` field is never read (leakage guard, asserted in code).
- **Data:** DataGolf API is the live provider (historical rounds, schedule, field,
  pre-tournament predictions). Redis caching (immutable archives cached long; live feeds
  short). Mock provider exists for tests.
- **Frontend:** React + TypeScript (Vite).
- **Infra:** Docker; Fly.io for deploy (activation/deploy are explicit user actions).

## The current model (the baseline all work is measured against)
- `golf_v1`, registered version **`0d2efade42ba`** (active, not necessarily deployed).
  Registry lineage: `136a5aca11d2 → a212ed166088 → d69cf2a7323f → 0d2efade42ba`.
- **v3 feature set (`v3_dg_preds`) = 18 features**, hash `18a5376f33f7…`. It is a strict
  superset of the prior 14-feature `v2_field_relative` (hash `bc91c96027e8`, unchanged):
  - **14 SG-based features:** absolute SG ratings (off-the-tee / approach / around-green
    / putting / total), recent **form index**, the five **field-relative** SG margins,
    **field strength**, **round count**, **score volatility**.
  - **4 external-model meta-features (new):** `dg_make_cut`, `dg_top_20`, `dg_top_10`
    (DataGolf's pre-tournament `baseline_history_fit` probabilities for the headroom
    markets), and `has_dg_pred` (cold-start indicator; the three DG probs are `NaN` —
    never 0.0 — when an event/player has no archive entry, and HistGBM routes NaN
    natively).
- **Trained on 35,804 examples** (26,853 train + 8,951 held out for calibration) from
  the **2018–2023 historical archive + 2024–2026 live data**, **through 2026-06-30**,
  with **365-day recency weighting** and a **730-day per-feature history window**
  computed as-of each example's date (leakage-safe).
- **Current validated performance (10-event production-regime backtest, block-bootstrap
  90% CI):**
  - **make-cut skill +0.246** [CI **+0.153, +0.350**] — genuine skill
  - **top-20 skill +0.141** [CI +0.115, +0.166] — genuine skill
  - top-10 skill +0.078 [CI +0.035, +0.109] — now genuine (was marginal under v2)
  - win / top-5 skill straddle 0 (coarse markets, as expected)
  - **Spearman(win, finish) +0.301**, **mean winner rank 32.2**, winner-in-top-10 ≈ 28%
  - 30-event holdout make-cut Brier improved **−0.024 (~11%)** vs the v2 baseline.

## How work is done here (the methodology — IMPORTANT for judging prompts)
Strict, disciplined ML-engineering loop, explicitly required by the user:
1. **Audit / analyze first** (often read-only) →
2. identify the **single highest-impact** change →
3. implement **only that one thing** →
4. **validate with objective metrics** (the rolling-origin backtest is the sole
   promotion gate; a read-only diagnostics pipeline gives per-player error analysis) →
5. explain results →
6. **STOP for approval.**
Other rules: no new features or UI pages unless explicitly asked; don't tune the
trainer/hyperparameters without evidence of need; if a change shows no
statistically meaningful improvement, **recommend reverting rather than iterating**.

Validation tooling (the promotion gate is now a **multi-regime** discipline):
- **10-event production-regime backtest** — trains at real deployment scale (~35k
  examples) and scores the 10 most-recent completed events out-of-sample. The primary
  gate: **lower block-bootstrap 90% CI bound > 0** on make-cut or top-20, no ranking
  regression.
- **30-event holdout** — the decisive tiebreaker (make-cut holdout Brier must improve).
  An 85-event data-starved cross-check is also used to surface small-data artifacts.
- **Block-bootstrap 90% CIs** resample whole *events* (the correct correlated unit).
- **Read-only diagnostics pipeline** — exports per-(player,event) predictions, feature
  values, permutation importances, calibration.
- A promotion requires the checks to **agree**; a single-split point estimate is never
  sufficient (this rule caught multiple false positives — see the record below).

## Experimental record (what's settled — do NOT re-litigate)
- ✅ **Field-relative SG — the original biggest win.** Adding "player vs. THIS field"
  fixed the model's worst pathology. Lesson: orthogonal, *event-level* information helps.
- ✅ **Historical-archive training data — VALIDATED + shipped, closed at 2018–2023.**
  DataGolf's `historical-raw-data` archive (pre-2024 events `get-schedule` can't reach)
  grew the training set ~6.5× (6,519 → 35,804). +2021–2023 and +2018–2020 each cleared
  the two-regime gate; **+2015–2017 REGRESSED** the make-cut holdout — 365-day recency
  attenuates pre-2018 examples to near-zero weight while staler baselines add noise.
- ✅ **Recency half-life = 365 days — re-validated at the 35.8k scale.** 180 / 545 / 730
  all failed the tighter gate (make-cut or ranking regression). 365d is the Pareto
  sweet spot.
- ✅ **DataGolf pre-tournament predictions (`v3_dg_preds`) — VALIDATED + ACTIVE; the
  largest single-change win in the program.** Folding DataGolf's own
  `baseline_history_fit` probabilities in as meta-features: **make-cut skill +0.065,
  top-20 +0.053, 30-event holdout make-cut Brier −0.024 (~11%)**, both gate checks
  agreed, permutation importance shows `dg_make_cut` dominates the make-cut market
  (larger than any SG feature). The **first EXTERNAL signal class to clear the gate**,
  after every internal transform was exhausted.
- 📌 **Player-history subspace = SATURATED.** Every transform of a player's own SG
  history failed the incremental gate: **Lever B** (longer history — ranking collapsed),
  **ceiling/upside** (redundant, symmetric noise, net ranking ≈ 0), **recency as a
  feature**, **empirical-Bayes shrinkage** (0/3 checks), **player random-effects prior**
  (10-event cleared but holdout make-cut regressed → 1/3, not promoted). ~2 latent skill
  dimensions are already captured. Lesson: **linear/standalone correlation overstates a
  feature's value inside the non-linear model; the only valid gate is incremental skill
  in the full backtest.**
- ❌ **Course information — no orthogonal signal.** A read-only residual-structure test
  showed finishing-residuals cluster only via the known field-strength bias (a **player
  main effect**, autocorr ≈ +0.40; course-specific increment ≈ +0.024 ≈ noise). An
  earlier course-fit feature also failed (thin ~33-venue coverage). Closed.
- ❌ **Weather — event-level wind scalar failed the gate decisively** (every market
  flat-to-worse). An event-level scalar cannot reorder within-field; only wind×player /
  wind×course *interactions* could, and those need paid pre-event forecast history.
- ❌ **Field-shape features** (field SG dispersion / depth / player-percentile) — failed
  the gate and **did not move the target weak-field residual.** Closed.
- ⚠️ **Layoff / staleness (`days_since_last_round`) — INCONCLUSIVE across three checks**
  (10-event +0.017 make-cut, 85-event null, production holdout worse). Not promoted.
- ❌ **Betting-market odds (Pinnacle OPENING lines as a feature) — no incremental signal
  over SG.** The book's win line is a noisier restatement of the same skill the
  field-relative SG features already extract at the top of the board, and it *diluted*
  the top-10/top-20 finish markets. Reverted. (Note: this closes odds-*as-a-feature*, a
  different question from the model beating the book, which it doesn't either.)

Infrastructure kept from these cycles: **block-bootstrap 90% CI** in the backtest
(promotion rule "lower CI > 0"); a **per-event rounds index** that cut field extraction
from O(players×events) to O(events) (made archive-scale builds feasible); the opt-in
**archive provider**; and the **read-only diagnostics + permutation-importance** exports.

## Data-capability facts (from a full DataGolf endpoint audit)
- **Every DataGolf API endpoint has been audited.** The Pre-Tournament Predictions
  Archive was the last viable lead and is now **exploited** (the v3 model). Verified
  leakage-safe: the archived predictions are genuine frozen pre-event snapshots (not
  refits), covering ~97–100% of 2020–2026 events at 100% within-event field coverage
  (2018–2019 cold-start to NaN, exactly the near-zero recency-weight years).
- The historical rounds payload we fetch also carries, at ~full coverage, fields we
  discard by design: real **course identity + par** (course program is closed as
  no-signal, not blocked), real tee times (a **proxy for absent weather**), and granular
  ball-striking (`driving_acc`, `gir`, `scrambling`, proximity — the inputs DataGolf
  already aggregated into the SG categories → **high redundancy risk**, the ceiling trap).
- **Player Skill Ratings / Skill Decompositions are SNAPSHOT-ONLY** (current values, no
  historical/as-of archive) → unusable as leakage-safe training features today.
- **Weather/wind remains absent** from all endpoints; it would require external sourcing
  + pre-event forecast history (leakage-sensitive) and would only help as *interactions*.

## The honest verdict on betting
The model is genuinely useful for the leaderboard/analytics (**make-cut skill ≈ +0.246,
top-20 ≈ +0.141** under v3) but does NOT beat a sharp sportsbook on any market;
winner-market skill ≈ 0. Large "edges" in the UI are model error, not value. The betting
view is a research/divergence tool, not a +EV product. Don't let prompts chase phantom
edges.

## Current strategic state (where we are right now)
- **Internal signal is exhausted; the external-model axis is now the live one.** Every
  transform of the SG/field data is closed (player-history saturated; course, weather,
  field-shape, layoff, shrinkage, odds-as-feature all closed). The v3 DataGolf
  meta-features **reopened the program along the external-model axis** and are the
  current active model.
- **What remains OPEN — a tracking question, not a build:** *does the model ever
  meaningfully override DataGolf's ordering at the TOP of the board (where it would
  matter), or do divergences stay in the low-information bottom third?* Early per-event
  grading shows the model **defers to the DataGolf prior at the sharp end** (almost no
  top-15 divergences across the first graded events). Resolving this requires **ongoing
  per-event tallying of top-15 divergences and their resolution** — a read-only diagnostic
  accumulated over many tournaments, **not a model change**.
- **What is CLOSED:** the DataGolf API is fully audited. The only remaining untested
  signal classes require **paid external data** (weather with interaction features,
  ShotLink shot-level data, course-architecture attributes) **or a DataGolf API
  expansion** (e.g. historical/as-of skill decompositions, currently snapshot-only).
  None are being pursued.
- Markets: **Make-Cut / Top-20 (and now Top-10) carry credible skill**; **Winner
  prediction is at or near a practical ceiling** (its driver is week-of variance /
  conditions, which the features cannot see).
- **Single-event grading caveat:** individual tournaments are high variance. No
  model/feature decision should rest on one event; a pattern must repeat across a much
  larger sample (minimum 2-of-3 on the same direction, ideally more) before it is even
  "worth tracking," let alone acting on.

## RUBRIC — how to judge a prompt the user is about to send
Rate each prompt on these. Flag any "no."
1. **One change at a time?** Does it ask for a single, scoped step — not a grab-bag?
2. **Evidence before engineering?** Does it gate building on a read-only test /
   metric, rather than jumping to feature design? (Premature "let's build feature X"
   is a red flag given the methodology.)
3. **Respects settled results?** Does it avoid re-running closed experiments
   (ceiling, Lever B, longer history) or re-sampling the saturated player-history
   subspace (more SG moments/windows/sub-stats) without a NEW reason?
4. **Asks for the right validation?** Does it expect backtest skill + ranking metrics
   (Spearman, winner rank), not just standalone correlation? (Standalone correlation
   has repeatedly misled here.)
5. **Honest about leakage & parity?** Anything using current-field-only data (e.g.
   market odds, live projections) as a model feature is a train/serve parity trap.
   Realized weather/tee outcomes are post-hoc leakage; only pre-event info is valid.
6. **Right target market?** Winner-market improvement is near-ceiling; prompts
   expecting big winner gains from player-history-style features are likely
   misguided. Make-cut / top-20 are where headroom is.
7. **Accurate framing?** Does the prompt state facts consistent with this briefing
   (model isn't sportsbook-beating; player-history saturated; course data now at full
   coverage)? Flag factual drift.
8. **Knows when to stop?** Good prompts accept "if no meaningful improvement, revert."

When a prompt fails the rubric, say which item, why, and suggest a tighter rephrasing.
