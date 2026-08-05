# 3M Open — Results & Model Grade

- **Event:** 3M Open, TPC Twin Cities — 2026-07-23 to 2026-07-26 (completed)
- **Graded:** 2026-07-29 · 143 of 144 players gradeable
- **Companion:** [pre-tournament report](2026-07-22-3m-open.md)

Grades **both** boards against actual results: DataGolf's pre-event archive (what Path A *intends* to serve) and the served v2 SG-only board (what production actually showed, per the serving bug documented in the pre-tournament report).

---

## Headline: the bug has a measurable cost

Brier score (lower is better) and skill vs. a base-rate baseline (higher is better):

| Market | DG raw Brier | Served v2 Brier | Base Brier | **DG skill** | **v2 skill** |
|--------|--------------|-----------------|------------|--------------|--------------|
| Win | 0.0072 | 0.0069 | 0.0069 | −0.032 | +0.001 |
| Top 5 | 0.0338 | 0.0349 | 0.0402 | **+0.159** | +0.131 |
| Top 10 | 0.0668 | 0.0702 | 0.0769 | **+0.131** | +0.087 |
| Top 20 | 0.1151 | 0.1237 | 0.1350 | **+0.147** | +0.084 |
| Make cut | 0.2170 | 0.2467 | 0.2485 | **+0.127** | +0.007 |

**DataGolf beat the served model on all four markets that carry skill.** The gap is widest exactly where the product claims its strongest market: on make-cut, DataGolf posted +0.127 skill while the served v2 board posted **+0.007 — statistically indistinguishable from just predicting the field base rate.** The bug is not cosmetic; it costs most of the make-cut and top-20 edge.

Win is noise for both (one winner in 143 players); DG's −0.032 reflects Scheffler being priced at 23.4% and finishing 2nd. A single event cannot separate win skill.

## Winner: Jackson Koivun

| | DataGolf | Served v2 |
|---|---|---|
| Win probability | 2.0% | 0.78% |
| Rank in field by win prob | **7th of 144** | 21st of 144 |

Ranking the eventual winner 7th in a 144-player field is a genuinely good pre-event call. The served board buried him at 21st — another concrete instance of the bug degrading output. Koivun is also the player carrying `sg_total=None` in the skill feed (thin PGA sample), so DataGolf's rating leaned on its own model rather than a rolling SG history.

## Actual top 10 vs. what each board said

| Finish | Player | DG win | DG top-20 | Served win |
|--------|--------|--------|-----------|------------|
| 1 | Jackson Koivun | 0.020 | 0.318 | 0.0078 |
| 2 | Scottie Scheffler | **0.234** | **0.782** | 0.0223 |
| T3 | Chandler Phillips | 0.002 | 0.097 | 0.0066 |
| T3 | Denny McCarthy | 0.006 | 0.187 | 0.0066 |
| T3 | Hideki Matsuyama | 0.027 | 0.374 | 0.0067 |
| T3 | Brian Harman | 0.010 | 0.242 | 0.0063 |
| T7 | Emiliano Grillo | 0.006 | 0.177 | 0.0066 |
| T7 | Davis Thompson | 0.008 | 0.205 | 0.0068 |
| 9 | Ben Kohles | 0.014 | 0.286 | 0.0099 |
| 10 | Gary Woodland | 0.010 | 0.214 | 0.0065 |

## Published picks — scorecard

**Top 5 win picks — 2 of 5 finished top 3**

| Pick | DG win | Finish |
|------|--------|--------|
| Scottie Scheffler | 23.4% | **2nd** ✅ |
| Maverick McNealy | 3.6% | 34th |
| Kurt Kitayama | 3.5% | 24th |
| Tom Kim | 2.9% | 20th |
| Hideki Matsuyama | 2.7% | **3rd** ✅ |

The headline call — Scheffler as a field-mismatch outlier — was nearly right: 2nd place, and he was the only player the model separated from the pack. Matsuyama at #5 finished T3.

**Value plays (top-20 market) — 3 of 5 hit**

| Pick | Finish | Hit? |
|------|--------|------|
| Scottie Scheffler | 2nd | ✅ |
| Tom Kim | 20th | ✅ (exactly T20) |
| Maverick McNealy | 34th | ❌ |
| Doug Ghim | missed cut | ❌ |
| Ben Kohles | 9th | ✅ |

Ben Kohles is the best evidence for the course-fit thesis: flagged on a **+0.25 course-fit adjustment** despite modest raw SG (+0.46), he finished 9th. Doug Ghim, flagged on the field's strongest course *history* (+0.123), missed the cut — history did not travel.

**Fades — 3 of 5 correct**

| Fade | Finish | Correct? |
|------|--------|----------|
| Gordon Sargent | missed cut | ✅ |
| Rasmus Højgaard | missed cut | ✅ |
| Stephan Jaeger | missed cut | ✅ |
| Jake Knapp | 13th | ❌ |
| Emiliano Grillo | **7th** | ❌ |

The three fades justified by weak SG all missed the cut. The two misses were the ones fading recent form rather than skill.

## What this week actually established

1. **DataGolf-direct beats the served board on every market with skill** — top-5 +0.159 vs +0.131, top-10 +0.131 vs +0.087, top-20 +0.147 vs +0.084, make-cut +0.127 vs +0.007. Path A's premise is validated by out-of-sample results; the bug preventing it from running is now quantified, not theoretical.
2. **The served v2 model has ~zero make-cut skill on this event** (+0.007), against the product's own claim that make-cut is its best-calibrated market. That claim currently describes a model the site is not serving.
3. **Course fit outperformed course history.** Kohles (+0.25 fit) → 9th; Ghim (+0.123 history) → missed cut. One event is not proof, but it is the first live datapoint on which decomposition signal to weight.
4. **Both boards ranked the winner outside the top 5**, which is the normal condition for golf win markets — the honest framing is that the model ranks the *distribution* well, not that it names winners.
