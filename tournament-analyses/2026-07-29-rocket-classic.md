# Rocket Classic — Pre-Tournament Model Report

- **Event:** Rocket Classic, Detroit Golf Club — starts 2026-07-30
- **Field:** 147 players (all DataGolf-covered, all with sportsbook odds)
- **Pulled as-of:** 2026-07-29
- **Sources:** DataGolf raw pre-tournament (`baseline_history_fit`, live), sportsbook consensus de-vigged to DataGolf field totals, DataGolf skill ratings + decompositions.

> **Same caveat as last week:** the live site still serves the v2 SG-only model, not DataGolf, because `CachingProviderWrapper` does not forward `get_pretournament_full_preds`. All numbers below are **DataGolf raw** — what Path A intends to serve. Last week's grading showed this is the right source: DG beat the served board on every market with skill (make-cut +0.127 vs +0.007).

---

## The short version

No Scheffler this week, and it shows: where the 3M Open had a +2.78 SG outlier, the Rocket Classic's favorite is **Cameron Young at 8.0%** — a normal, competitive top of the board. Nine players sit between 2.6% and 8.0% to win. This is a much flatter field, so edges come from the top-20 and make-cut markets rather than from picking a winner.

## Top 5 Win Picks

| # | Player | DG win | Fair market | SG total | Off-tee | Approach |
|---|--------|--------|-------------|----------|---------|----------|
| 1 | **Cameron Young** | **8.0%** | 6.1% | **+1.93** | +0.74 | +0.78 |
| 2 | Chris Gotterup | 5.0% | 3.8% | +1.64 | +0.70 | +0.57 |
| 3 | Xander Schauffele | 4.5% | 3.6% | +1.68 | +0.71 | +0.63 |
| 4 | Si Woo Kim | 3.8% | 3.2% | +1.66 | +0.46 | +0.74 |
| 5 | Patrick Cantlay | 3.4% | 2.5% | +1.44 | +0.37 | +0.67 |

Young leads on the most complete profile in the field: best SG total (+1.93) built on **both** off-tee (+0.74) and approach (+0.78), not one category carrying him. The model is more bullish than the market on him (8.0% vs 6.1%).

## Best Value Plays — DataGolf above the de-vigged market (top-20 market)

| Player | DG top-20 | Fair market | Edge | Driver |
|--------|-----------|-------------|------|--------|
| **J.J. Spaun** | 37.9% | 29.8% | **+8.1%** | **course history +0.231** — the standout in the field |
| **Cameron Young** | 53.4% | 45.8% | +7.6% | best all-round SG (+1.93) |
| **Chris Gotterup** | 43.9% | 36.8% | +7.0% | longest driver of the leaders (+16.9 yds), SG +1.64 |
| Ben Griffin | 37.3% | 30.9% | +6.3% | putting +0.45, SG +1.39 |
| Ryan Gerard | 32.6% | 26.9% | +5.8% | SG +1.26, priced as a tier below |

**J.J. Spaun is the week's most interesting name.** His raw skill (+1.19 SG) is the weakest of the value group, but DataGolf's decomposition gives him a **+0.231 course-history adjustment — roughly 3× any other contender's** (Young +0.075, Clark +0.056, Griffin +0.052). He is the one player this week whose edge comes from the venue rather than form.

Worth flagging honestly: last week the course-history pick (Doug Ghim, +0.123) missed the cut while the course-*fit* pick (Ben Kohles, +0.25) finished 9th. Spaun is the same category of bet that just failed once.

## Best Top-20 Picks

Young 53.4% · Gotterup 43.9% · Schauffele 42.7% · Si Woo Kim 42.3% · Cantlay 38.8% · Spaun 37.9% · Griffin 37.3% · Clark 36.6% · Henley 35.0% · Matsuyama 35.0%.

## Safest Make-Cut Picks

Young 82.6% · Si Woo Kim 77.7% · Gotterup 77.6% · Schauffele 77.2% · Cantlay 76.2% · Griffin 75.6% · Spaun 75.4% · Matsuyama 73.9%.

Note the ceiling: 82.6% is the highest make-cut probability in the field, versus 92.5% for Scheffler last week. Without a dominant favorite, even the safest play is meaningfully less safe.

## Biggest Fades — market rates them for top-20, DataGolf doesn't

| Player | Fair market | DG top-20 | Gap | Why |
|--------|-------------|-----------|-----|-----|
| **William Jennings** | 10.3% | 3.8% | **−6.5%** | no established SG rating (thin sample) |
| **Seamus Power** | 17.2% | 11.3% | −5.9% | SG total **+0.015** — essentially field-average |
| Lucas Glover | 14.1% | 10.0% | −4.0% | SG **−0.205**, below field average |
| Billy Horschel | 15.5% | 11.8% | −3.7% | SG +0.034 |
| **Jordan Spieth** | 19.3% | 16.7% | −2.7% | SG +0.554 — priced on name above form |

The pattern is consistent: the market pays for reputation (Spieth, Horschel, Glover), the model pays for current strokes-gained.

## Model Insights

1. **No outlier this week.** The favorite's 8.0% win probability is a third of Scheffler's 23.4% last week. Nine players cluster between 2.6% and 8.0% — a genuine toss-up at the top, so the model's useful signal lives in top-20/make-cut, not win.
2. **Detroit Golf Club reads as a distance course — but the model still won't pay up for it.** Gotterup (+16.9 yds), Schauffele (+13.1), Young (+11.5) are among the field's longest, yet every one of their driving-distance adjustments is **negative** (−0.017, −0.013, −0.012). Same anti-narrative signal as TPC Twin Cities: length correlates with the good players here, it isn't independently rewarded.
3. **Course fit is negative for essentially the entire top of the board** (Young −0.065, Si Woo Kim −0.073, Griffin −0.070, Cantlay −0.055). The model sees no one in the leading group as an especially good stylistic match — which is part of why the field is flat.
4. **J.J. Spaun's +0.231 course-history adjustment is the single largest feature-level edge in the field this week**, and it is the one thing separating him from a dozen similarly-skilled players.
5. **Model and market agree on the shape, disagree on the level.** DataGolf rates all nine leading contenders *above* their fair-market top-20 price. That is a systematic tilt, not nine independent reads — it likely means the book is spreading probability further down the field than the model does.

## Methodology Notes

- **What the model evaluates:** five nested markets (win ⊆ top-5 ⊆ top-10 ⊆ top-20 ⊆ make-cut), forced coherent and field-normalized (win → 1, top-5 → 5, …). Underlying signal is strokes-gained by category (off-tee / approach / around-green / putting), field-relative margins, recent form, and round-to-round volatility.
- **Source used here:** DataGolf's own pre-event probabilities plus its decomposition adjustments (course history, course fit, driving distance/accuracy). Validated last week as the stronger source on every market with skill.
- **Market comparison:** sportsbook consensus with DataGolf's baseline excluded, de-vigged by scaling each market to its true field total; edge = model probability − fair implied probability.
- **Reliability ordering:** make-cut and top-20 carry genuine measured skill; win and top-5 are thin (one winner per event) and should be read as directional only.
