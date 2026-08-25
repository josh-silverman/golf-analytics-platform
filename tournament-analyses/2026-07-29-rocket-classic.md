# Rocket Classic — Pre-Tournament Model Report

- **Event:** Rocket Classic, Detroit Golf Club — starts 2026-07-30
- **Field:** 147 players (all DataGolf-covered, all with sportsbook odds)
- **Pulled as-of:** 2026-07-29
- **Sources:** DataGolf raw pre-tournament (`baseline_history_fit`, live), sportsbook consensus de-vigged to DataGolf field totals, DataGolf skill ratings + decompositions.

> **Per-player probabilities removed 2026-08-25.** DataGolf's terms are personal
> use only, no redistribution, and this repository is public (see
> [ledger.md](../docs/ledger.md) §2.8). What that leaves is the ordering, the
> direction of each model-versus-market disagreement, and the reasoning, all of
> which is the analytical content. Absolute probabilities, strokes-gained
> ratings and decomposition adjustments are held privately.

> **Same caveat as last week:** the live site still serves the v2 SG-only model, not DataGolf, because `CachingProviderWrapper` does not forward `get_pretournament_full_preds`. All reads below are **DataGolf raw**, which is what Path A intends to serve. Last week's grading showed this is the right source: DG beat the served board on every market with skill.

---

## The short version

No Scheffler this week, and it shows. Where the 3M Open had a single dominant strokes-gained outlier, the Rocket Classic's favorite is **Cameron Young** at roughly a third of last week's favorite's win probability. Nine players cluster inside a narrow band at the top of the win market. This is a much flatter field, so edges come from the top-20 and make-cut markets rather than from picking a winner.

## Top 5 Win Picks

In model order:

| # | Player | Model vs de-vigged market | Primary driver |
|---|--------|---------------------------|----------------|
| 1 | **Cameron Young** | model higher | best SG total in the field, built on **both** off-tee and approach |
| 2 | Chris Gotterup | model higher | second-best SG total, longest driver of the leaders |
| 3 | Xander Schauffele | model higher | strong off-tee and approach, marginally behind Gotterup on SG total |
| 4 | Si Woo Kim | model higher | approach-led profile |
| 5 | Patrick Cantlay | model higher | approach-led, weakest off-tee of the five |

Young leads on the most complete profile in the field: the best SG total, and it is built on both off-tee and approach rather than one category carrying him. The model is more bullish than the market on him.

## Best Value Plays — DataGolf above the de-vigged market (top-20 market)

Ranked by the size of the model-over-market gap:

| Player | Rank by edge | Driver |
|--------|--------------|--------|
| **J.J. Spaun** | 1 | **course history is the standout adjustment in the field**, roughly 3x any other contender's |
| **Cameron Young** | 2 | best all-round SG |
| **Chris Gotterup** | 3 | longest driver of the leaders, second-best SG total |
| Ben Griffin | 4 | putting-led, mid-pack SG total |
| Ryan Gerard | 5 | priced a tier below his SG total |

**J.J. Spaun is the week's most interesting name.** His raw skill is the weakest of the value group, but DataGolf's decomposition gives him a course-history adjustment roughly 3x any other contender's. He is the one player this week whose edge comes from the venue rather than form.

Worth flagging honestly: last week the course-history pick (Doug Ghim) missed the cut while the course-*fit* pick (Ben Kohles) finished 9th. Spaun is the same category of bet that just failed once.

## Best Top-20 Picks

In model order: Young · Gotterup · Schauffele · Si Woo Kim · Cantlay · Spaun · Griffin · Clark · Henley · Matsuyama.

## Safest Make-Cut Picks

In model order: Young · Si Woo Kim · Gotterup · Schauffele · Cantlay · Griffin · Spaun · Matsuyama.

Note the ceiling: the safest make-cut play this week sits about ten percentage points below last week's safest. Without a dominant favorite, even the safest play is meaningfully less safe.

## Biggest Fades — market rates them for top-20, DataGolf doesn't

Ranked by the size of the market-over-model gap:

| Player | Rank by gap | Why |
|--------|-------------|-----|
| **William Jennings** | 1 | no established SG rating (thin sample) |
| **Seamus Power** | 2 | SG total essentially field-average |
| Lucas Glover | 3 | SG total below field average |
| Billy Horschel | 4 | SG total marginally above field average |
| **Jordan Spieth** | 5 | modest positive SG total, priced on name above form |

The pattern is consistent: the market pays for reputation (Spieth, Horschel, Glover), the model pays for current strokes-gained.

## Model Insights

1. **No outlier this week.** The favorite's win probability is about a third of Scheffler's last week. Nine players cluster in a narrow band at the top, a genuine toss-up, so the model's useful signal lives in top-20/make-cut rather than win.
2. **Detroit Golf Club reads as a distance course, but the model still won't pay up for it.** Gotterup, Schauffele and Young are among the field's longest drivers, yet every one of their driving-distance adjustments is **negative**. Same anti-narrative signal as TPC Twin Cities: length correlates with the good players here, it isn't independently rewarded.
3. **Course fit is negative for essentially the entire top of the board** (Young, Si Woo Kim, Griffin and Cantlay all negative). The model sees no one in the leading group as an especially good stylistic match, which is part of why the field is flat.
4. **J.J. Spaun's course-history adjustment is the single largest feature-level edge in the field this week**, and it is the one thing separating him from a dozen similarly-skilled players.
5. **Model and market agree on the shape, disagree on the level.** DataGolf rates all nine leading contenders *above* their fair-market top-20 price. That is a systematic tilt, not nine independent reads. It likely means the book is spreading probability further down the field than the model does.

## Methodology Notes

- **What the model evaluates:** five nested markets (win ⊆ top-5 ⊆ top-10 ⊆ top-20 ⊆ make-cut), forced coherent and field-normalized (win → 1, top-5 → 5, …). Underlying signal is strokes-gained by category (off-tee / approach / around-green / putting), field-relative margins, recent form, and round-to-round volatility.
- **Source used here:** DataGolf's own pre-event probabilities plus its decomposition adjustments (course history, course fit, driving distance/accuracy). Validated last week as the stronger source on every market with skill.
- **Market comparison:** sportsbook consensus with DataGolf's baseline excluded, de-vigged by scaling each market to its true field total; edge = model probability − fair implied probability.
- **Reliability ordering:** make-cut and top-20 carry genuine measured skill; win and top-5 are thin (one winner per event) and should be read as directional only.
