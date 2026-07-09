# Technical Due Diligence: PGA Prediction Platform

*Independent senior ML engineer review, conducted as pre-adoption due diligence — as if this repository were being evaluated internally before adoption by a professional sports analytics organization. Findings are evidence-based, drawn from the committed source, tests, CI config, and registry artifacts.*

**Scope note on verifiability:** several headline claims (the DataGolf archive being a frozen pre-event snapshot, the 30-event holdout results, permutation-importance findings) come from session-era analysis recorded in `docs/`, not from committed, re-runnable code. These are marked explicitly. Everything else below is verified against source.

---

## 1. Model architecture

**Design.** Five independent binary `HistGradientBoostingClassifier` heads (win/top-5/top-10/top-20/make-cut), per-market calibration (Platt for rare markets, isotonic for dense — `calibration.py:52`, a correct and unusually thoughtful choice), post-hoc nesting coherence via running max (`predictions.py:43-68`), and field-sum normalization (`predictions.py:87-125`).

**Challenge — the architecture is statistically inefficient by construction.** Finish position is one ordinal outcome; slicing it into five binary problems throws away shared information, then requires two post-hoc patches (coherence max, field normalization) to repair contradictions the architecture itself created. The normalization patch also isn't a fixed point: rescaling then re-applying the coherence max (`predictions.py:118-124`) can push market sums off their targets again. A rank-based model (ordinal regression, Plackett–Luce, or simulation from a strength+variance model — which `docs/architecture` doc 01 itself names as the intended "Approach C" that was never built) would produce coherent, field-normalized probabilities natively. The current design is a reasonable stepping stone that has quietly become permanent.

**Serving pipeline.** Train/serve parity is genuinely well-engineered: one `FeatureExtractor.extract_field` code path for training, backtest, and serving (`features.py:161`), an as-of-anchored 730-day rounds window (`features.py:47`), and serving that caps `as_of` at event eve (`predictions.py:196`). This is better than most industrial pipelines encountered in review.

**However, the evaluator does not score what production serves.** The backtest scores `coherent_outcomes(model.predict(...))` (`backtest.py:341-349`) but production additionally applies `normalize_field` (`predictions.py:243`). The comment at `backtest.py:330` claiming "the backtest scores what production serves" is **false**. Ranking metrics are unaffected (per-market scaling is monotone within an event), but every Brier/skill/ECE number for win and top-5 describes probabilities users never see. The headline "+0.00 win skill" may be wrong in either direction for the served product.

**A second serving hazard that could not be verified as safe:** the live DG-preds path ignores `event_id` entirely (`datagolf_provider.py:1355-1357`) — it fetches "whatever event DataGolf currently features." If a user requests predictions for an upcoming event that is *not* DG's current event, wrong-event probabilities are silently joined by player id. No guard exists.

**Reproducibility — a real gap.** `version_id = hash(feature_set_hash, through_date, hyperparameters)` (`registry.py:54-72`). The **training data itself is not hashed and never snapshotted**. If DataGolf revises historical rounds (they do), retraining produces a *different model with the same version id*, and the registry's "idempotent training" claim becomes silently false. Artifacts are pickles with no recorded sklearn version (deps are `>=`, not pins, in `pyproject.toml`; `uv.lock` pins the env but the artifact metadata records nothing), and calibration imports sklearn's private `_SigmoidCalibration` (`calibration.py:24`) — a version-fragility landmine for artifact loading.

**Experiment management.** No tracker (MLflow/W&B/even CSV). Experiments live as 17 one-off scripts in `backend/diagnostics/` plus prose in `docs/project-summary.md`. The prose record is unusually disciplined (pre-registered gates, recorded reversions), but results are not machine-readable, not re-runnable as committed artifacts, and depend on mutable upstream data. A second engineer could not reproduce the v3 promotion decision from the repo alone.

**Code quality.** High. Strict mypy, ruff, 267 backend tests + 42 frontend tests, CI with frozen deps, dataclass-frozen domain models, excellent docstrings that explain *why*. Two smells: the builder reaches into a provider private method (`_fetch_historical_training_events`, `training.py:181`, self-acknowledged with `noqa: SLF001`), and `_vectorize`'s silent `features.get(name, 0.0)` default (`trainer.py:93`) — a known footgun (it nearly corrupted the v3 NaN semantics) that survives as a trap for the next feature author.

## 2. Validation methodology

**Strengths first, because they're real:** walk-forward evaluation with strict as-of discipline; block bootstrap resampling *events* rather than rows (`backtest.py:179-217`) — the correct correlated unit, which most practitioners get wrong; chronological (never random) calibration split (`calibration.py:171-187`); a "lower CI > 0" promotion rule; a documented culture of reverting failed experiments.

**Now the problems, in descending severity:**

1. **The promotion gate tests the wrong hypothesis.** The CI is computed on each arm's *absolute* skill separately. Promotion decisions (v3 vs v2) compared point estimates of two arms whose predictions are extremely correlated on the same 10 events. The correct test is a **paired bootstrap on the per-event skill delta**, which would have far tighter intervals and would directly answer "is v3 better than v2?" Nothing in the repo computes a delta CI. The reported "+0.065 make-cut improvement" has no confidence interval attached anywhere in the repo.

2. **The two "independent" gates are nested.** The 10-event and 30-event checks (`backtest_arm.py --test-events 10|30`) share the same 10 most-recent events — the 10-event window is a subset of the 30-event window. "Both checks agree" is presented as convergent evidence but is substantially one correlated observation.

3. **Test-set exhaustion.** The experimental record documents ~12+ experiments adjudicated against the same most-recent-events windows. Each look leaks information; the gate's false-positive rate is now unknowable. There is no untouched, final holdout. This is the classic garden of forking paths, partially mitigated by the reversion discipline but not eliminated.

4. **"Rolling-origin" is an overstatement.** `backtest.py:285-306` trains **once** before the window and scores all 10 events with a progressively staler model. A true rolling evaluation (retrain per event) would both match deployment and yield more honest per-event variance. With ~35k examples and event-level parallelism this is affordable.

5. **The public "track record" is in-sample.** `compute_track_record` grades the *active* model (trained through 2026-06-30) on recent completed events — events whose outcomes were in its training set. Features are pre-event, but the trees saw the labels. The leaderboard presents this as "Track record (last 8 events)" adjacent to genuinely out-of-sample backtest numbers. To a professional reviewer this is the most damaging presentation issue in the product: honest numbers and hindsight numbers share a page without distinction.

6. **The production model discards its freshest data from the trees.** `fit_calibrated` registers the model whose base learner saw only the earliest 75% (`calibration.py:217-224`); the newest 8,951 examples — precisely the ones the 365-day recency weighting says matter most — only tune calibrators. Standard practice (cross-fitted calibration, or refit-on-full with frozen calibrators) would recover them. This is free accuracy being left on the table in every deploy.

7. **Leakage protection** is otherwise strong. The `fin_text` assertion (`datagolf_provider.py:1447`) is admittedly near-tautological (the `markets` dict is built from a fixed 3-key tuple and could never contain `fin_text`; also `assert` vanishes under `-O`) — the real guard is the explicit key whitelist, which is sound. The critical *unverifiable* assumption: that the archive's `baseline_history_fit` is a frozen pre-event snapshot, and that the **live endpoint's identically-named field is generated by the same upstream model** as the archive's. The snapshot-authenticity check was session work (Scheffler trajectory); no committed test re-verifies it, and archive/live distributional parity is untested anywhere. If live and archive DG predictions differ systematically, v3 has a train/serve skew on its most important features.

**Are the reported improvements convincing?** Directionally yes — the make-cut/top-20 skill is large, consistent across (correlated) windows, and mechanistically plausible. But the *magnitudes* carry unquantified uncertainty (no delta CIs, nested gates, reused test windows), and the win-market numbers describe pre-normalization probabilities. Overall: probably real, imprecisely measured, and evaluated by a gate that has been reused past its statistical budget.

## 3. Feature engineering

| Class | Assessment |
|---|---|
| **Time-decayed SG ratings (5)** | Sound. Below-average priors for thin histories (`player.py:23-30`) are a smart fix for the phantom-edge problem. 60-day half-life asserted, not swept in committed code. **Exhausted** per the (uncommitted) saturation experiments. |
| **Field-relative margins (5) + field strength** | The right idea — relative skill is what win probability is. But note: `field_rel_sg_X = sg_X − mean(sg_X)` is an exact linear function of features the GBDT already has plus a per-event constant. Trees can't easily synthesize cross-row aggregates, so it *does* add value, but 5 margins + 5 absolutes + field strength is ~2 effective dimensions dressed as 11. **Redundancy is high; headroom zero.** |
| **Form index, round count, volatility** | Reasonable confidence/variance proxies. `score_volatility` was designed for a Monte Carlo engine that doesn't exist — it now just feeds the classifier. **Exhausted.** |
| **DG meta-features (4)** | The one genuinely orthogonal signal, and honest engineering around missingness (NaN, never 0; explicit indicator). But permutation importance reportedly shows `dg_make_cut` *dominating* the make-cut head — which raises the uncomfortable question the repo never answers (see §5, blind spot #1). **Not exhausted — but its remaining upside belongs to DataGolf, not this codebase.** |

**Verdict:** internal (SG-derived) feature space is convincingly saturated; the documented closures (course, weather scalar, field shape, odds-as-feature) are credible. The only live axis is external signal, and it is currently a single-vendor dependency.

## 4. Remaining improvement opportunities (not yet explored)

| # | Opportunity | ROI | Difficulty |
|---|---|---|---|
| 1 | **Head-to-head benchmark: DG's raw `baseline_history_fit` as a standalone predictor vs. v3, same events, same Brier/ranking suite.** The single most important unanswered question: does this model add *anything* over its dominant input? The Benchmark page (`analytics.py:140+`) displays side-by-side probabilities but computes zero accuracy comparison. Read-only, one diagnostic script. | **High** | Low |
| 2 | **Paired-delta bootstrap gate** (CI on per-event skill difference between arms) + one pristine, never-before-used holdout period reserved for final promotion decisions. Fixes the two worst methodology gaps at once. | **High** | Low |
| 3 | **Recover the calibration slice for the trees** — cross-fitted (K-fold-in-time) calibration or refit-on-full with frozen calibrators. ~33% more effective training data at the recency-weighted end, every deploy, forever. | **High** | Medium |
| 4 | **Score the served pipeline in the backtest** (apply `normalize_field` before metrics) and report both raw and served numbers. Restores trust in the headline figures. | Medium-High | Low |
| 5 | **Ordinal / rank-native model** (Plackett–Luce over finish, or LambdaMART-style listwise objective) replacing five binary heads — architecturally cleaner, guaranteed-coherent, and the only plausible route to residual win-market signal. | Medium | High |
| 6 | **Honest live track record** — persist each event's pre-event board *at prediction time* (model version stamped), grade only boards produced by models trained before the event. Turns the in-sample UI stat into a genuine accumulating out-of-sample record. | Medium (product trust: High) | Low |
| 7 | Dataset content hash into `version_id` + a data snapshot per registered model. | Medium | Low |

Explicitly *not* recommended: more SG-window transforms, course/weather scalar retries — the closure evidence is adequate.

## 5. Blind spots

1. **"Is the model just DataGolf with extra steps?"** — untested. If v3 ≈ monotone recalibration of DG's own probabilities, the platform's core asset is a UI over a $30/mo API. Given `dg_make_cut`'s reported dominance, this is the elephant in the room. (Experiment #1 above settles it in an afternoon.)
2. **Archive/live DG parity** — assumed, never measured. A one-week diagnostic (capture live preds pre-event, diff against the archive row post-event) would settle it.
3. **In-sample track record on the UI** — untested assumption that users read it as informal; a professional adopter will read it as fraud-adjacent once discovered.
4. **No monitoring** — no live calibration drift tracking, no alerting when DG coverage silently drops to cold-start NaN for a whole field (the board would degrade to v2-quality with no signal anywhere).
5. **Withdrawals** — a pre-cut WD trains and scores as `made_cut=0` (`training.py:222-225` skips only ACTIVE and position-less MADE_CUT). WDs are ~injury/personal noise, not skill; small but systematic label contamination in the flagship market.
6. **Missing benchmarks that professionals would demand:** closing-line value on real odds over time; comparison vs. a naive "DG + isotonic" baseline; per-season performance stability (all metrics are pooled).
7. **Technical debt:** pickle artifacts + private sklearn API; mutable-upstream reproducibility; the 0.0-default vectorizer; single-vendor data dependency with no contract tests against live API schema drift (fixtures only).

## 6. Overall assessment

| Reference class | Verdict |
|---|---|
| Hobby project | **Far above.** Not comparable. |
| Strong portfolio project | **Above.** Top-percentile: real validation culture, documented negative results, production serving, honest UI framing. |
| Graduate research | **Comparable in discipline, below in statistical rigor.** The gate-reuse, nested holdouts, and missing paired tests would draw reviewer objections; the leakage discipline and negative-result record would draw praise. |
| Professional sports analytics team | **Below, with a clear path.** Missing: experiment tracking, data versioning, paired statistical tests, live shadow evaluation, monitoring, and the DG-standalone benchmark. The parity engineering, however, matches or beats industry norm. |
| Commercial prediction products (DataGolf itself, syndicates) | **Not competitive as a *predictor*, by its own honest admission** (doesn't beat the book; its best feature *is* a commercial competitor's output). Competitive as an analytics/presentation layer. |

---

## Executive summary

A disciplined, well-engineered solo ML platform whose train/serve parity, leakage hygiene, and experiment culture are genuinely strong — and whose headline numbers are nonetheless less trustworthy than presented, because the evaluation gate tests absolute rather than paired skill, its two "independent" checks share test events, the backtest doesn't score the served pipeline, and the UI's track record is in-sample. The model's dominant signal is a competitor's published predictions, and the repo never answers whether it outperforms that input standalone. Architecture (5 independent binary heads + post-hoc patches) is a stepping stone that hardened into a foundation. Fixing the measurement layer costs days and would materially change confidence in every number; the DG-standalone benchmark could either validate the entire enterprise or reveal it to be an expensive recalibration of someone else's model.

## Top 5 strengths
1. Single-code-path train/serve parity with as-of-anchored windows — rarely done this well.
2. Event-level block bootstrap and chronological calibration splits — correct correlated-data instincts.
3. Documented negative results and reversion discipline; settled questions stay settled.
4. Leakage engineering: eve-capped serving, forbidden-field whitelisting, NaN cold-starts.
5. Code quality: strict typing, 300+ tests, CI, self-explanatory docstrings.

## Top 5 weaknesses
1. No paired-delta significance test behind any promotion decision.
2. Backtest scores a pipeline production doesn't serve (missing `normalize_field`).
3. In-sample "track record" presented on the product surface.
4. No data versioning — version ids don't identify the data, artifacts aren't reproducible.
5. Registered models never train on their freshest 25% of examples.

## Top 5 highest-ROI next experiments
1. DG-standalone vs. v3 head-to-head Brier/ranking benchmark (read-only).
2. Paired per-event delta bootstrap + one pristine final-holdout window.
3. Cross-fitted calibration to recover the held-out 25% for the trees.
4. Backtest the served (normalized) probabilities; publish both.
5. Prediction-time board persistence → honest accumulating live track record.

## Biggest risk to future model improvement

**Evaluation-capital exhaustion on a possibly-derivative model.** The same few test events have adjudicated every decision, so the gate's ability to distinguish real gains from noise is degraded exactly when the remaining gains are smallest — and if the model's edge is mostly a recalibration of DataGolf's output, future "improvements" will optimize noise around a signal the project doesn't own, while a single upstream vendor change (API schema, model revision, pricing) can silently invalidate both the model and its historical validation record.

---

*Reviewed against commit history as of 2026-07-08. File/line references point to `backend/app/` paths relative to the repository root.*
