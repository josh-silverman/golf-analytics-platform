# Tournament Analyses

Evidence-first pre-tournament model reports — one per event. Each is the raw
analyst pass over that week's model outputs (win / top-5 / top-10 / top-20 /
make-cut), compared against DataGolf's own probabilities and the sportsbook
market, with every claim traceable to the actual numbers rather than golf
narrative. These are the working notes behind the portfolio articles, not the
polished articles themselves.

## How each report is produced

The `predictions` pipeline is run for the event (Path A serving intent:
DataGolf-direct for covered players, the v2 SG-only model for cold-start), then:

1. Pull the served board plus DataGolf's raw `baseline_history_fit`
   probabilities and the de-vigged sportsbook consensus.
2. Rank each market; find where the model is most confident and where it most
   diverges from the market.
3. Explain the top names with the underlying statistics — strokes-gained by
   category, driving distance, and DataGolf's course-fit / course-history
   decomposition adjustments.

Any serving or data-quality caveat discovered that week is recorded at the top
of the report, so a reader knows exactly how much to trust each market.

## Index

| Date | Event | Report | Headline |
|------|-------|--------|----------|
| 2026-07-30 | Rocket Classic | [2026-07-29-rocket-classic.md](2026-07-29-rocket-classic.md) | Flat field, no outlier — Cameron Young 8.0% to win; J.J. Spaun's +0.231 course-history adjustment is the week's biggest single edge |
| 2026-07-23 | 3M Open | [pre](2026-07-22-3m-open.md) · [**results**](2026-07-27-3m-open-results.md) | Scheffler a historic field-mismatch (DG win 23.7%) → finished 2nd. Grading confirmed DataGolf beats the served board on every market with skill |

## Results grading

Once an event completes, a companion `-results.md` grades the predictions against
what actually happened — Brier score and skill vs. a base-rate baseline for each
market, plus a scorecard for every published pick. Where a serving caveat applied
that week, both boards are graded so the cost of the discrepancy is measured
rather than asserted.
