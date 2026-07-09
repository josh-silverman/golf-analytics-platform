# Design Document: Rank-Native Model (research track `rank_v1`)

*Design only — no implementation. Companion to [technical-due-diligence.md](technical-due-diligence.md). Motivated by five benchmark experiments (joint-GBDT stacking, full residual, shrunk residual, win/top_5 comparison) that showed the current architecture — `golf_v1`, five independent `HistGradientBoostingClassifier` heads plus the `coherent_outcomes` and `normalize_field` post-hoc patches — does not beat DataGolf's raw predictions on any of the five markets for DG-covered players.*

---

## 0. Root cause and the goal of this track

Finish position is **one ordinal outcome**. The current design slices it into five binary problems, discarding the shared ordinal structure, then repairs the resulting contradictions with two post-hoc patches:
- `coherent_outcomes` (running max, [predictions.py:43](backend/app/services/predictions.py#L43)) — forces win ≤ top-5 ≤ … ≤ make-cut back into nesting the independent heads violated.
- `normalize_field` ([predictions.py:87](backend/app/services/predictions.py#L87)) — rescales each market so the field sums to its true total (1 winner, 5 top-5s, …), which the independent per-player heads never respect.

A rank-native model represents the finish ordering directly, so both properties hold **by construction** — the patches disappear.

**Honest framing of the ceiling (this governs the whole track).** The session's residual experiment showed the SG feature space carries only ~0.0004 Brier of *orthogonal* signal over DG's own predictions, and the win/top_5 benchmark showed DG out-ranks `v3` even on markets `v3` doesn't stack. That strongly suggests the limiting factor is **information in the 14 SG features, not the architecture.** A rank-native model can (a) remove the patches, (b) plausibly extract a bit more ranking from the same features via a ranking-appropriate loss, and (c) model `make_cut`/field structure honestly — but it **cannot manufacture signal the features don't contain.** The realistic upside is "match DG's ranking more cleanly and drop the patches," not "decisively beat DG." Section 6 pre-registers a kill criterion calibrated to exactly this.

---

## Scope & location decision

**Location: new subpackage `backend/app/ml/rank_v1/`** (confirming the proposed location; reasoning below). Module breakdown:
- `rank_v1/dataset.py` — reshape existing `TrainingData` into grouped (per-event) ranking format.
- `rank_v1/trainer.py` — fit the scorer; produce a `RankModel` artifact + hyperparameters dict.
- `rank_v1/model.py` — the `RankModel` (field-level `predict_field`, see below) + save/load.
- `rank_v1/markets.py` — derive the five market probabilities from a ranking output.

**Reuse, unmodified:** `CatalogService`, `DataProvider`/`DataGolfProvider`, `FeatureExtractor` + all feature primitives (`app/features/*`), `TrainingDataBuilder`, the `backtest.py` scoring primitives (`_brier`, `_spearman`, `_bootstrap_skill_ci`), and `ModelRegistry`.

**Registry isolation — zero code changes, zero production risk.** `ModelRegistry` is namespaced by model *name* ([registry.py:75](backend/app/ml/registry.py#L75)); `rank_v1` registers under a new name in the same filesystem registry (`models/rank_v1/…`), never touching `models/golf_v1/` or `_active.txt`. `version_id = hash(feature_set_hash, through_date, hyperparameters)` ([registry.py:54](backend/app/ml/registry.py#L54)) works unchanged. The serving path (`PredictionService`, deps, API) is **not modified** during research — evaluation runs through the offline benchmark harness only.

**One necessary new interface.** The existing `Model.predict(features: dict) -> dict` is **per-player**; a ranking/simulation model is inherently **field-level** (a player's win probability depends on the whole field). Introduce a `RankModel` ABC with `predict_field(field: dict[pid, dict[str,float]]) -> dict[pid, dict[str,float]]` — separate from `Model`, so `golf_v1`'s interface is untouched. This is not new complexity; it *absorbs* the field-level `normalize_field` step (already bolted on after per-player `predict`) into the model where it belongs.

---

## 1. Model family selection

| | **Plackett–Luce (listwise LTR)** | **Ordinal regression** | **Strength + variance simulation** |
|---|---|---|---|
| **What it is** | Probabilistic model over full rankings; each player gets a latent worth `v_i = exp(s_i(features))`; `P(ranking) = ∏ₖ v_{π(k)} / Σ_{j≥k} v_{π(j)}` (the "exploded logit"). ListMLE loss = exact PL negative log-likelihood. | Predicts the ordered finish bucket via a cumulative-link (proportional-odds) model: `P(finish ≤ threshold)` monotone in thresholds. | Each player gets latent skill `μ_i(features)` + spread `σ_i`; simulate the field's scores N times, rank each sim, read market frequencies. |
| **Library (no custom optimizer)** | LightGBM `rank_xendcg`/`lambdarank`, XGBoost `rank:ndcg` (**both need OpenMP** — see below); or `allRank`/PyTorch `ListMLE`/`ListNet` (no OpenMP, heavy torch dep); `choix` is **not** a fit (fixed-item worths, not feature-conditional). | `mord`, `statsmodels` `OrderedModel`; or Frank–Hall reduction to K−1 monotone binary GBDTs (reuses existing `HistGradientBoosting`). | **No new library:** `μ` = existing `HistGradientBoostingRegressor` (sklearn), `σ` = existing `score_volatility` feature or a small variance model, simulation = `numpy`. |
| **Input** | One row per player **grouped by event** + a relevance label derived from finish. | One row per player, target = ordered finish bucket. | One row per player (μ regressor) + field composition. |
| **Natural output** | A score per player (log-worth). | `P(finish ≤ k)` for each threshold. | Empirical finish distribution per player from the sims. |
| **Coherent 5 markets w/o patches?** | **Yes** via Gumbel sampling from worths (`P(rank=1)=win`, `P(rank≤5)=top5`, …, `P(rank≤cut)=make_cut`) — nested by construction. Worths optimize *order*, so per-market **calibration** (isotonic) is needed for probability quality (honest calibration, not a coherence patch). | **Partial.** Cumulative link fixes internal nesting (removes `coherent_outcomes`) but is **per-player marginal** — it does **not** respect the field-sum constraint, so `normalize_field` would still be needed. Fixes half the root cause. | **Yes, fully.** Every sim has exactly one winner and a real cut line, so win/top-k/make_cut are coherent **and** field-normalized natively. `make_cut` handled directly as `P(rank ≤ cut line)`. |
| **`make_cut` (flagship, most signal)** | Needs cut-line threshold applied to sampled ranks — workable but bolted on. | Natural as one cumulative threshold. | **Native and honest** — the simulation has a cut. |
| **New heavy dependency?** | Yes (OpenMP via LightGBM/XGB, *contradicting the documented [trainer.py:9](backend/app/ml/trainer.py#L9) decision to avoid it*), or torch. | No (if Frank–Hall) / small (`mord`). | **None.** |

**Recommendation: the strength + variance simulation model, as primary** — with its latent-skill scorer trained in a ranking-aware way (details below). Reasoning, in priority order:

1. **It is the only family that removes *both* patches natively** and produces all five markets — including `make_cut`, the market with the most real signal — coherent and field-normalized by construction. Ordinal fixes only nesting; PL needs a cut-line bolt-on and post-hoc calibration.
2. **It requires no new heavy dependency**, uniquely respecting the project's deliberate, documented dependency minimalism ([trainer.py:9-15](backend/app/ml/trainer.py#L9-L15)). `μ` reuses the existing sklearn GBDT; the simulation is numpy. PL's best implementations reintroduce OpenMP (the exact thing the project avoided) or add torch.
3. **It is the project's original stated intent** ("Approach C", the skill→simulation model the docs describe and that `score_volatility`'s docstring was written for but never built) — and it puts the already-extracted, currently-underused `score_volatility` feature to work as `σ`.
4. **Ranking quality is not sacrificed** if the `μ` scorer is trained ranking-aware. Start dependency-free by fitting `μ` on a **within-event rank-transformed target** (finish percentile), which pushes the regressor toward correct ordering without a true listwise loss; escalate to a genuine listwise trainer only if the ranking ceiling isn't met (staged, see §5).

**PL-listwise LTR is the recommended alternative** if pure ranking is the sole objective and a new dependency is acceptable — it optimizes the exact axis (order) the kill criterion measures, most directly. It becomes the fallback if the simulation's `μ`-via-rank-regression underperforms on Spearman. **Ordinal regression is dominated** and not recommended: it fixes only half the root cause (still needs `normalize_field`) and does not optimize ranking.

---

## 2. Feature reuse

**The 14 v2 SG features feed the new model with essentially no transformation.** They are already per-player numeric values from `FeatureExtractor.extract_field`, and the five `field_rel_sg_*` margins are *already field-relative* — ideal inputs for a model whose job is ordering players within a field.

Reshaping required, by family:
- **Simulation (recommended):** `μ` regressor takes **one row per player, unchanged** — identical shape to today. `σ` is the existing `score_volatility` value (or a small learned model on the same features). **No reshape.**
- **PL / listwise LTR (alternative):** needs a **group structure** — the same per-player rows plus a `group`/`query-id` array giving players-per-event. `extract_field` already operates per event, so grouping is a bookkeeping step, not a feature change. **Listwise avoids pairwise expansion** (no player-pair rows needed); only per-player rows + group ids.

**No feature needs redefinition or a version bump** (`v2_field_relative` hash `bc91c96027e8` stays fixed). The one new *engineered target*, not feature, is the relevance/finish encoding (§4).

---

## 3. Evaluation framework

**Native ranking metrics** (the model's own objective quality):
- **Spearman(score, −finish) per event, averaged** — already computed by [backtest.py:164](backend/app/ml/backtest.py#L164); **directly comparable** to the DG-standalone and `v3` Spearmans established this session (DG holdout Spearman ≈ +0.29 make_cut, +0.37 top_20/top_10/top_5/win).
- **NDCG@k (k = 5, 10, 20)** and **top-k precision** (did the predicted top-k contain the actual top-k finishers).
- **Mean/median predicted rank of the actual winner** — already in `RankingMetrics`.
- **Held-out full-ranking log-likelihood** (PL NLL) — only if the PL alternative is used.

**Deriving the five market probabilities from a ranking output (for apples-to-apples):**
- **Simulation:** the sims already yield `P(rank=1)=win`, `P(rank≤5)=top5`, …, `P(rank≤cut)=make_cut` — coherent and normalized.
- **PL:** Gumbel-max sampling — add i.i.d. Gumbel noise to log-worths, sort, repeat N times; read the same rank frequencies.
- **Calibration:** because ranking objectives optimize order, pass derived probabilities through **per-market isotonic calibration** on a chronological held-out slice, reusing the existing [calibration.py](backend/app/ml/calibration.py) infrastructure. This is honest calibration, **not** a coherence patch — coherence already holds.

**Apples-to-apples harness (critical):** score the derived market probabilities with the **same `_brier`/`_spearman` primitives, on the same 26-event / 3,037-covered-row holdout**, and run the **same paired-delta block bootstrap (2,000 reps, 90% CI, event-resampled)** used this session — against **both** DG-standalone **and** `v3`. The new model must be dropped into the identical evaluation so its numbers sit directly beside the benchmarks already on record.

---

## 4. Data requirements

**Nothing beyond what is already extracted** — same training window, same `as_of = start_date − 1` discipline, same 730-day feature window, same leakage posture. Specifically:
- **Finish position + made-cut status** (the ordinal signal) are already present on `TournamentEntry` and already consumed by `labels_from_entry` ([training.py:71](backend/app/ml/training.py#L71)) — the rank model simply **stops binarizing** them. Finish is a post-event *label*, never a feature; leakage posture is unchanged.
- **Field grouping** is already available (`extract_field` is per-event).
- **No new external data, no new provider calls, no new endpoints.**

**Three data-shaping decisions (new targets, not new data sources) — flag these:**
1. **Relevance/finish encoding.** Map finish → a ranking target: within-event finish percentile (for the recommended rank-regression `μ`), or graded relevance `field_size − position` (for NDCG/PL). Choice affects results; must be pre-specified.
2. **Missed-cut players are censored.** They have `final_position = None` and share the tail. Assign them a shared worst-tier relevance / a censored rank block. This is the single most consequential shaping choice and interacts with the `make_cut` market.
3. **Cut-line derivation.** To read `make_cut` from a simulated/sampled rank, the model needs each event's cut position (typically top 65 + ties, but some events have no cut). Derivable from existing field data — the backtest already computes an analogous `worst_placement` ([backtest.py:373](backend/app/ml/backtest.py#L373)) — but must be handled per event (including no-cut events).

---

## 5. Realistic scope and effort

Single engineer, focused, staged to reach a **validated benchmark comparable to the DG-standalone result**:

| Phase | Work | Effort |
|---|---|---|
| 0 | Dataset reshape (`dataset.py`): grouped format, relevance encoding, MC-censoring, cut-line derivation | 0.5–1 wk |
| 1 | `μ` scorer via rank-transformed regression (no new dep) + `σ` from `score_volatility`; sanity-check ranking metrics | 1 wk |
| 2 | Simulation layer (`markets.py`) → five coherent markets + per-market isotonic calibration | 1–1.5 wk |
| 3 | Drop into the existing benchmark harness; paired-delta bootstrap vs DG **and** `v3` on the 26-event holdout | 0.5–1 wk |

**First validated answer: ~3.5–4.5 weeks** on the dependency-free simulation path. Add **1–2 weeks** if Phase 1's ranking is insufficient and the `μ` scorer must escalate to a true listwise LTR trainer (LightGBM/allRank), which also incurs the OpenMP/torch dependency decision. **Budget 4–6 weeks** for a trustworthy first comparison.

**Riskiest unknown (could derail the track):** **the ceiling may be the features, not the architecture.** The residual experiment quantified only ~0.0004 Brier of orthogonal SG signal over DG, and DG out-ranks `v3` even on unstacked markets. It is entirely plausible that a rank-native model on the **same 14 SG features** lands at the same Spearman as DG — because a better *loss function* cannot add *information* the inputs lack. If so, weeks of architecture work reproduce `v3`'s position more elegantly but no more accurately. This is the primary derailment risk and the reason for a strict, pre-registered kill criterion. Secondary risks: simulation calibration (score correlation structure — weather/course move a whole field together, which an i.i.d.-noise sim ignores) and MC-censoring choices distorting `make_cut`.

---

## 6. Kill criteria (pre-registered)

Evaluated on the **same 26-event / 3,037-covered-row holdout**, with the **same paired-delta block bootstrap (2,000 reps, 90% CI)** used this session. Decide after **≤ 6 weeks** of reasonable effort.

**PRIMARY KILL (ranking):** If the rank-native model's **paired-delta Spearman vs DG-standalone has a 90% CI that straddles zero on both `make_cut` and `top_20`** (i.e., it fails to *statistically* out-rank DG on either signal market) → **stop; default to Path A** (serve DG's calibrated probabilities directly for covered players, `v2` for the ~5% cold-start). Rationale: if a properly rank-native architecture cannot beat DG's ranking on the same features, the ceiling is informational, and further architecture work is not the lever.

**EARLY KILL (Phase 3, hard stop):** If the first honest benchmark shows the derived markets are **significantly *worse* than `v3`** (paired-delta CI excludes zero on the negative side vs `v3`, not just vs DG) on any signal market → abandon immediately; the added complexity fails to match even the incumbent.

**REGRESSION GUARD:** Even if the primary ranking bar is met, if any market's **Brier-skill delta vs DG is significantly negative** → the ranking win is being bought with calibration loss; do not promote without resolving.

**PARTIAL-SUCCESS (explicit decision, not a default):** If the model **ties** DG on ranking (CI straddles zero) **but** provably removes both post-hoc patches and is simpler/more maintainable → that is a legitimate *architecture/code-quality* win, **not** a predictive-value win. Decide it explicitly as an engineering tradeoff; do **not** let "it's more elegant" substitute for the accuracy bar. Absent an explicit decision to adopt on elegance grounds, tie ⇒ Path A.

**SUCCESS (continue/productionize):** Paired-delta Spearman vs DG-standalone **CI lower bound > 0 on both `make_cut` and `top_20`**, with no significant Brier-skill regression on any market, and coherence/normalization provably patch-free. Only then specify a serving-path integration (a separate design).

---

*Design complete. No model, training, or evaluation code written. Next action, if approved: Phase 0 dataset reshape under `backend/app/ml/rank_v1/dataset.py`, against the pre-registered kill criteria above.*
