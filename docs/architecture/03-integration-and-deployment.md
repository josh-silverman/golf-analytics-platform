 03-integration-and-deployment.md

PGA Tour Analytics Platform — Final Architecture Pass
This document closes out planning. After this we're ready to start building.

1. DataGolf Integration Architecture
The Real DataGolf API Surface
DataGolf exposes a flat REST surface under https://feeds.datagolf.com/ with API-key-as-query-param authentication, JSON or CSV responses, and a 45 requests/minute global rate limit (with a 5-minute suspension if exceeded). That rate limit is the single most important constraint shaping the integration.
The endpoint families relevant to this project:
Family	Endpoint	Used For
General	/get-player-list	Player roster sync, ID mapping
General	/get-schedule	Tournament calendar
General	/field-updates	This week's field, tee times
Predictions	/preds/get-dg-rankings	Top 500 player skill estimates (calibration benchmark)
Predictions	/preds/pre-tournament	DataGolf's own pre-tournament forecasts (benchmark for our model)
Predictions	/preds/pre-tournament-archive	Historical predictions (model evaluation)
Predictions	/preds/player-decompositions	Per-player SG breakdown for upcoming event
Predictions	/preds/skill-ratings	Player SG skill estimates
Predictions	/preds/approach-skill	Detailed approach stats by yardage bucket
Live	/preds/in-play	Live finish probabilities (5-min refresh)
Live	/preds/live-tournament-stats	Live SG breakdown per player
Live	/preds/live-hole-stats	Hole-by-hole scoring averages
Betting	/betting-tools/outrights	Sportsbook odds for win/T5/T10/T20/MC across 11 books
Betting	/betting-tools/matchups	H2H and 3-ball odds
Historical Raw	/historical-raw-data/event-list	Available historical events
Historical Raw	/historical-raw-data/rounds	The training data source — round-level SG back to 2004 for PGA
Historical Event	/historical-event-data/events	Finishes, earnings, FedEx points
Historical Odds	/historical-odds/outrights	Opening/closing lines for backtesting
Historical Odds	/historical-odds/matchups	Historical matchup lines
DFS	/historical-dfs-data/points	DFS salaries & ownership
The Critical Realization
DataGolf does NOT expose shot-level data through the API. The previous schema design assumed shot-level granularity available; that needs to be amended. The smallest unit DataGolf gives us is the round, which includes pre-computed sg_ott, sg_app, sg_arg, sg_putt, sg_t2g, sg_total, distance, accuracy, GIR, proximity, scrambling, etc.
This is actually liberating — it means we don't have to build our own strokes-gained engine from raw shot tracking data, because DataGolf already publishes the SG values. Our work is downstream: skill estimation, feature engineering, simulation, calibration, betting edge.
Schema amendment: the shots table from the previous design becomes optional/aspirational. The rounds table becomes the granular unit. Mock data generation should match this — generate round-level SG values directly rather than synthesizing shots and aggregating.
Mapping DataGolf → Our Domain

```
DataGolf Endpoint                  →   Our Tables                    →   Our Adapter Method
─────────────────────────────────────────────────────────────────────────────────────────────
/get-player-list                   →   players                       →   list_players()
/get-schedule                      →   tournaments, courses          →   list_tournaments(season)
/field-updates                     →   tournament_entries            →   get_tournament_field(t_id)
/historical-raw-data/rounds        →   rounds, tournament_entries    →   get_rounds(t_id) / backfill
/preds/skill-ratings               →   (benchmark only — not stored  →   get_dg_skill_ratings()
                                       as primary; we compute ours)
/preds/pre-tournament              →   (benchmark predictions)       →   get_dg_predictions(t_id)
/preds/in-play                     →   (live benchmark)              →   get_live_predictions(t_id)
/preds/live-tournament-stats       →   rounds (in-progress updates)  →   get_live_stats(t_id)
/betting-tools/outrights           →   betting_lines                 →   get_betting_lines(t_id)
/historical-odds/outrights         →   betting_lines (backfilled)    →   get_historical_lines(...)
```
The DataGolfProvider Implementation Plan
The DataGolfProvider class implements the DataProvider interface defined earlier. Its internals:

```
┌──────────────────────────────────────────────────────────────────┐
│                      DataGolfProvider                             │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              DataGolfHTTPClient (httpx.AsyncClient)         │ │
│  │  - Base URL: https://feeds.datagolf.com                    │ │
│  │  - Auto-appends ?key=... to every request                  │ │
│  │  - JSON-only (we never use CSV)                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                    │
│  ┌───────────────────────────┴───────────────────────────────┐  │
│  │             RateLimiter (token bucket)                     │  │
│  │  - 45 tokens, refill rate 0.75/sec                         │  │
│  │  - Awaits when bucket empty (never trips 5-min suspension) │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                    │
│  ┌───────────────────────────┴───────────────────────────────┐  │
│  │           Retry Layer (tenacity)                           │  │
│  │  - Exponential backoff on 5xx, network errors             │  │
│  │  - NO retry on 4xx (those are our bug, not their failure) │  │
│  │  - Special handling for 429: long sleep, then resume      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                    │
│  ┌───────────────────────────┴───────────────────────────────┐  │
│  │      Response Adapter Layer (per-endpoint translators)     │  │
│  │  - DataGolf JSON → our Pydantic domain models             │  │
│  │  - Validates shapes, raises on missing required fields     │  │
│  │  - Records any unexpected fields (logged, not failed)      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                    │
│  ┌───────────────────────────┴───────────────────────────────┐  │
│  │          Public DataProvider Interface Methods             │  │
│  │  - Each method orchestrates 1+ underlying calls            │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```
The Rate Limiter Is the Centerpiece
At 45 requests/minute, the API is slow for bulk operations. Backfilling 5 years × 45 events × 1 call each is 225 calls, which at the rate limit takes ~5 minutes minimum. Backfilling all 22 tours and all available years could be thousands of calls. The rate limiter must be:
* Global to the provider (singleton per process) — not per-method
* Token-bucket-based with a burst capacity of ~30 and a refill of 0.75/sec, leaving 25% headroom below the actual limit. Never operate at the ceiling.
* Async-aware — await the bucket; don't sleep-block, since the pipeline workers will fan out calls in parallel
* Observable — emit metrics on tokens-remaining and wait-time-distribution
A hiring manager who's done API integrations will absolutely look for this. The wrong answer ("I just put a time.sleep(1.5) between calls") tells them you've never run a real pipeline.
Caching and Freshness
Different endpoints have very different freshness requirements:
Endpoint Type	TTL	Justification
get-player-list	24 hours	Players don't get added often
get-schedule	12 hours	Schedule rarely changes mid-season
historical-raw-data/rounds	Forever (immutable)	Past tournaments don't change
field-updates	15 minutes	WDs and tee times shift on tournament week
preds/pre-tournament	30 minutes	DataGolf updates these a few times daily
preds/in-play	0 (don't cache)	5-min refresh is the whole point
betting-tools/outrights	2 minutes	Lines move; stale data is misleading
historical-odds/*	Forever (immutable)	Past lines don't change
The CachingProviderWrapper decorator I described earlier consults a per-method TTL table. Cache backend is Redis, keys are deterministic from method + args.
This caching strategy actually solves the rate limit problem. With sensible TTLs, the steady-state read load against DataGolf drops by ~95% after the initial backfill. Total API budget for normal operation falls well within 45 req/min.
Backfill Strategy
The historical data backfill is a one-time-plus-incremental operation, and it's where you'll burn the most API budget:

```
Phase 1: Reference data       (~10 calls)
  - Player list
  - Schedule for current + past 3 seasons
  - Event lists for raw data and odds

Phase 2: Historical rounds    (~500-1500 calls)
  - PGA Tour, 2019-2025
  - One call per (tour, event_id, year)
  - Run as Prefect flow with explicit pacing

Phase 3: Historical odds      (~100-300 calls)
  - Same events × handful of books
  - Only run if backtesting betting edge

Phase 4: Predictions archive  (~100 calls)
  - For model comparison/benchmarking

Total: ~700-2000 calls, ~16-45 minutes of wall time at rate limit
```
Backfill is resumable and idempotent. State (which events have been backfilled) is tracked in a backfill_progress table. If the process dies, restarting resumes from the last successful event. This is the kind of operational maturity that distinguishes real engineers from people who've only built toys.
Validating That Our Mock Provider Matches the Real Shape
This is the test that proves the abstraction works: when DataGolf access lands, point the contract test suite at the DataGolf provider with a sandbox key. If it passes the same tests the mock provider passes, you can swap with confidence. If it doesn't, you've localized the problem to the adapter layer where it belongs.
The Benchmark Play
DataGolf publishes their own pre-tournament predictions. We have a once-in-a-portfolio opportunity here: train our model, predict the same field, and compare. Even getting within shouting distance of DataGolf's calibration on a held-out set is genuinely impressive (they're one of the best public golf models in existence). You don't have to beat them. You just have to come close and analyze the gap honestly.
A dedicated "Model vs. DataGolf" page in the dashboard makes this comparison legible to anyone scrolling through. It's the single most powerful demo asset the project can have. Make this page.

2. Backend API Contract Design
Design Principles
Three rules:
1. The frontend never knows about Postgres or DataGolf. It sees a clean REST surface defined by Pydantic models. Source-of-data is an implementation detail.
2. Versioned at the URL level (/api/v1/...). Pragmatic, obvious, costs nothing.
3. Resources first, actions second. Standard REST for reads; explicit action endpoints for things like "run a simulation" that aren't naturally CRUD.
Route Map

```
GET    /api/v1/healthz                                        # liveness
GET    /api/v1/readyz                                         # readiness (db + redis)
GET    /api/v1/meta/data-freshness                            # when did we last sync

# Players
GET    /api/v1/players                                        # search/paginate
GET    /api/v1/players/{player_id}
GET    /api/v1/players/{player_id}/recent-rounds              # ?limit=20
GET    /api/v1/players/{player_id}/skill-history              # ratings over time
GET    /api/v1/players/{player_id}/course-history/{course_id}

# Tournaments
GET    /api/v1/tournaments                                    # ?season=2026&status=upcoming
GET    /api/v1/tournaments/{tournament_id}
GET    /api/v1/tournaments/{tournament_id}/field
GET    /api/v1/tournaments/{tournament_id}/results            # for completed
GET    /api/v1/tournaments/{tournament_id}/leaderboard        # for in-progress
GET    /api/v1/tournaments/current                            # convenience: this week's PGA event

# Predictions & Simulations
GET    /api/v1/predictions/{tournament_id}                    # latest active-model predictions
GET    /api/v1/predictions/{tournament_id}/compare-datagolf   # the benchmark page
POST   /api/v1/simulations                                    # trigger a sim run
GET    /api/v1/simulations/{run_id}                           # poll status + results
GET    /api/v1/simulations/{run_id}/stream                    # SSE for live progress

# Betting
GET    /api/v1/betting/{tournament_id}/edges                  # +EV bets per market
GET    /api/v1/betting/{tournament_id}/lines                  # raw odds across books

# Models
GET    /api/v1/models                                         # registered model versions
GET    /api/v1/models/{model_id}/metrics                      # Brier, log-loss, calibration
GET    /api/v1/models/{model_id}/feature-importance

# Analytics
GET    /api/v1/analytics/sg-leaders                           # ?category=app&period=l24
GET    /api/v1/analytics/calibration                          # reliability data for the model
GET    /api/v1/analytics/field-strength-history
```
Response Shape Conventions
Every list endpoint returns a pagination envelope:

```json
{
  "data": [...],
  "page": { "next_cursor": "...", "has_more": true, "total": 247 },
  "meta": { "as_of": "2026-05-26T14:00:00Z", "source": "model:v3" }
}
```
The meta.as_of and meta.source fields are present on every response that involves computed data. The frontend can show "Predictions generated 2 hours ago, model v3.2" without needing custom logic per endpoint. This is the kind of small consistency decision that makes a UI feel trustworthy.
Single-resource responses skip the data wrapper but keep meta. Errors are RFC 7807 problem-detail format. OpenAPI is auto-generated by FastAPI and served at /api/docs — include a link from the homepage. Interviewers do look at the OpenAPI page.
Background Job Pattern
Simulations are long-running. The pattern:

```
POST /api/v1/simulations           → 202 Accepted, returns { run_id, status: "queued" }
GET  /api/v1/simulations/{run_id}  → poll, returns { status, progress, results? }
GET  .../stream                    → SSE; emits progress events as the sim runs
```
This is the standard async job pattern. The worker is an arq process (lighter than Celery, Redis-backed, fully async — matches the FastAPI async story). State lives in Postgres (simulation_runs.status); Redis is only used for the queue and SSE pub/sub.

3. Frontend Product / UI Architecture
This is where the project either feels like a polished product or like a homework assignment. We're going to design it like a product.
Visual Identity & Design Language
Theme: Premium dark, sportsbook-meets-Bloomberg. Think DraftKings + Bloomberg Terminal + Linear. Dense information, sharp typography, generous use of color only for meaningful signal.
Color palette (Tailwind config):

```
Background:    #0A0E1A  (near-black, slight blue cast — not pure #000 which looks cheap)
Surface:       #131826  (cards/panels)
Surface-2:     #1A2032  (elevated panels)
Border:        #232B40  (subtle, ~10% opacity white over surface)

Text primary:    #F0F2F8
Text secondary:  #9BA3B7
Text tertiary:   #5E6680

Accent:        #4FD1C5  (teal — primary brand, used sparingly)
Positive:      #22C55E  (green — +EV bets, gains, made cuts)
Negative:      #EF4444  (red — -EV, losses, missed cuts)
Warning:       #F59E0B  (amber — cut bubble, marginal calls)
Neutral chart: #6366F1, #8B5CF6, #EC4899  (purple/magenta family for variety)
```
The teal accent is the project's signature color. Use it for active states, the logo, and one or two key callouts per page — never as wall-to-wall paint. Sparseness makes it feel premium.
Typography:
* Headings: Inter or Geist (Geist is trendier; both look excellent in dark mode)
* Body: same as headings
* Numerics: a tabular monospace (JetBrains Mono or Geist Mono). Stats and probabilities ALWAYS render in tabular numerics so columns of numbers align perfectly. This single decision contributes more to "looks like a real analytics product" than almost anything else.
Density: Compact but breathable. Default text size 14px, line-height 1.5. Card padding 16-20px. Table row height 36-40px. Resist the urge to use whitespace like a marketing site — analytics products are dense by nature, and density signals seriousness.
Page-by-Page Layout
1. Dashboard (/) — the landing page, the "wow on open" page.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  PGA TOUR ANALYTICS                              [Tournament selector ▾] │  ← Top nav
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────────────┐  ┌─────────────────────────────────────┐    │
│  │  THIS WEEK             │  │  MODEL CONFIDENCE                   │    │
│  │  The Masters           │  │                                     │    │
│  │  Augusta National      │  │  [Calibration mini-chart]           │    │
│  │  Apr 10–13, 2026       │  │  Brier: 0.142   Log-loss: 0.421     │    │
│  │  Field: 91 players     │  │  Last updated: 2h ago               │    │
│  └────────────────────────┘  └─────────────────────────────────────┘    │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  TOP CONTENDERS                              [Sort: Win ▾]       │   │
│  │  ─────────────────────────────────────────────────────────────   │   │
│  │  Rank  Player              Win    T5    T10   Make Cut   SG/Rd   │   │
│  │   1    Scottie Scheffler   12.4%  38%   54%   93%        +2.31   │   │
│  │   2    Rory McIlroy         8.7%  31%   46%   91%        +2.08   │   │
│  │   ...                                                            │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌────────────────────────┐  ┌────────────────────────┐                 │
│  │ +EV BETS              │  │  FIELD STRENGTH HEATMAP │                 │
│  │ ──────────────────    │  │  [Recharts SG by player]│                 │
│  │ Scheffler Win  +18%   │  │                         │                 │
│  │ McIlroy T10    +12%   │  │                         │                 │
│  │ ...                   │  │                         │                 │
│  └────────────────────────┘  └────────────────────────┘                 │
└──────────────────────────────────────────────────────────────────────────┘
```
2. Tournament Detail (/tournaments/[id]) — drill-down view.
Tabs: Predictions | Simulation | Field | Course Fit | Betting Edges | Live (only if in-progress)
The simulation tab is special — clicking "Run new simulation" kicks off a job and shows live progress via SSE: probabilities updating as iterations stream in. This is the single most impressive interactive moment in the app. Spend time on it.
3. Player Profile (/players/[id]) — the player deep-dive.
Layout: hero header (name, country flag, current DG rank, current overall rating), then tabs:
* Form — rolling SG charts, last 20 rounds with sparklines per category
* Skill breakdown — SG:OTT / APP / ARG / PUTT decomposition over time
* Course history — wherever they're playing this week, plus career-level course stats
* Predictions — current tournament predictions if entered
4. Model Lab (/model) — the ML-engineering showcase page.
This is the page that signals "the person who built this knows ML." Includes:
* Model registry table (versions, training dates, training data through)
* Calibration plots (reliability diagram with confidence bands)
* Brier score and log-loss over time
* Feature importance (horizontal bar chart with SHAP values if you go that far)
* Model vs. DataGolf comparison — head-to-head Brier scores on common events
* Error analysis: where does the model miss?
Most candidates' projects don't have a page like this. Having one is a massive differentiator.
5. Betting (/betting) — sportsbook-style edge browser.
The most "fun" page visually. Looks like a sportsbook but every row has a tiny model-probability vs. implied-probability comparison and a calculated edge percentage.

```
┌────────────────────────────────────────────────────────────────────────────┐
│  EDGES — The Masters                                  [Filter: All books ▾]│
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  Player          Market   Book        Odds    Model   Edge   EV    Kelly  │
│  ─────────────   ──────   ─────────   ────    ─────   ────   ────  ─────  │
│  Scheffler       Win      DraftKings  +650    12.4%   +14%   +0.18  1.2%  │
│  Scheffler       Win      FanDuel     +700    12.4%   +18%   +0.22  1.6%  │  ← best book
│  McIlroy         Top 10   BetMGM      +110    46.0%    +3%   +0.06  0.4%  │
│  ...                                                                       │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```
Color the Edge column from red (-EV) to green (+EV) on a continuous scale. Highlight the best book per row.
6. Methodology (/methodology) — the "how this works" page.
Often skipped, hugely valuable. Explains the model, the simulation, the data sources. Has architecture diagrams (the same ones from your README). For a hiring manager browsing the live app, this is the page that closes the deal.
Component Hierarchy

```
src/
├── app/                          # Next.js App Router OR React Router routes
│   ├── layout.tsx                # AppShell wrapper
│   ├── page.tsx                  # Dashboard
│   ├── tournaments/
│   │   ├── page.tsx
│   │   └── [id]/page.tsx
│   ├── players/
│   │   ├── page.tsx
│   │   └── [id]/page.tsx
│   ├── model/page.tsx
│   ├── betting/page.tsx
│   └── methodology/page.tsx
│
├── components/
│   ├── primitives/               # Buttons, Inputs, Tabs, Tooltip, Dialog, etc.
│   │   └── (Radix-based)
│   ├── layout/
│   │   ├── AppShell.tsx
│   │   ├── TopNav.tsx
│   │   └── TournamentSelector.tsx
│   ├── data-display/
│   │   ├── DataTable.tsx         # The workhorse — sortable, virtualized
│   │   ├── ProbabilityBar.tsx    # Inline horizontal bar for probabilities
│   │   ├── DeltaIndicator.tsx    # +1.2 / -0.8 colored deltas
│   │   ├── SparklineCell.tsx     # Inline sparkline for tables
│   │   └── StatCard.tsx
│   ├── charts/
│   │   ├── primitives/           # Axis, Grid, Tooltip — shared D3 building blocks
│   │   ├── CalibrationPlot.tsx
│   │   ├── SGRollingChart.tsx
│   │   ├── ProbabilityDistribution.tsx
│   │   ├── FieldStrengthHeatmap.tsx
│   │   └── custom/               # The bespoke D3 work
│   │       ├── SGRadialBreakdown.tsx
│   │       └── SimulationOutcomeViz.tsx
│   └── feature/                  # Domain-specific composed components
│       ├── prediction/
│       │   ├── ContendersTable.tsx
│       │   ├── PredictionRow.tsx
│       │   └── ModelComparison.tsx
│       ├── betting/
│       │   ├── EdgesTable.tsx
│       │   └── KellySizingCard.tsx
│       └── simulation/
│           ├── SimulationRunner.tsx
│           └── LiveProgressViz.tsx
│
├── lib/
│   ├── api/                      # API client (TanStack Query hooks)
│   ├── format/                   # number/odds/date formatters
│   └── colors/                   # color scales (e.g., red→green for edges)
│
├── store/                        # Zustand stores (UI state only)
│   └── ui-store.ts
│
└── styles/
    └── globals.css               # Tailwind base + CSS vars
```
Charting Strategy
Don't pick one library and force everything through it. Use the right tool per chart type:
Chart Type	Library	Why
Standard line/bar/area charts	Recharts	Composable, declarative, dark-mode-friendly out of the box
Tables with embedded mini-charts	Custom with TanStack Table + d3-shape	Sparklines need to be tiny and tight
Custom visualizations (the showpieces)	D3 directly	No library exists for what we want
Real-time updating sim viz	Custom Canvas + requestAnimationFrame	DOM nodes don't scale to 156 players × 10k iters
The Two Custom D3 Visualizations
Custom Viz #1: The SG Radial Breakdown — a player skill profile as a radar/spider chart but redesigned. Four axes (SG:OTT, APP, ARG, PUTT) with the player's percentile rank as the radius, overlaid with the field average and the top-10 average bands. Animated entry on player page load. Compared side-by-side on the matchup pages. One of the signature visualizations.
Custom Viz #2: Simulation Outcome Stream — when a simulation is running, show a live-updating "river" of finishing positions. As iterations stream in, each player has a horizontal density strip showing where they're finishing across the 10k iterations. The strip is colored by density (darker = more iterations finished there), with markers at the win/T5/T10/cut thresholds. As iterations accumulate, the strips sharpen from noisy to crisp. This is the kind of visualization nobody else's portfolio project has. Build this even if it takes an extra week.
A back-of-napkin sketch:

```
Scheffler   ▓▓▓▓██████▓▓▓▒▒░░░░░ ░░░░ ░  ░     ░         (finishes mostly 1-15)
McIlroy     ▒▓▓▓██████▓▓▒▒░░░░░ ░░░  ░   ░  ░             (similar, slight right shift)
Schauffele  ░▒▓▓▓████▓▓▒▒░░░░░░  ░░░  ░  ░  ░    ░
            └─────────┴─────────┴─────────┴─────────┘
            1         25        50        75        100   ← finishing position
                    │T10     │T20         │CUT
```
Motion & Animation
Three rules:
1. Animations are for state transitions, not decoration. A probability ticking up should animate; a page-load hero shouldn't spin in pointlessly.
2. Spring physics, not eased timing. Use Framer Motion's spring presets. Easing functions feel computer-y; springs feel physical.
3. 150-250ms for UI transitions, 400-600ms for chart entrances, 800ms+ only for the "wow" moment on first dashboard load.
Specific moments worth animating:
* Numbers counting up when probabilities change (Framer Motion's useMotionValue + useTransform)
* Table rows reordering when sort changes (FLIP via layout prop)
* Chart entrance animations on page load (staggered, 50ms per element)
* Live simulation: the outcome stream visualization continuously updating as data streams
* Probability bars sliding to new values when fresh predictions arrive
* Page transitions: subtle fade + 4px slide, 200ms — never spinning carousels or anything aggressive
Responsive Strategy
Three breakpoints, designed mobile-up:
* Mobile (<768px): Single-column, cards stack, tables become card lists, side nav becomes hamburger. The custom D3 viz simplifies (drop the field-average overlay on the radar; collapse the simulation stream to top 20 players only).
* Tablet (768-1280px): Two-column where it fits, side nav becomes icon-only rail.
* Desktop (>1280px): Full layout, side nav with labels, multi-column dashboards.
* Wide (>1600px): Don't stretch; max content width 1600px centered. Side margins go gray, content stays focused. This is what Bloomberg/Linear do; full-width on huge monitors makes apps feel cheap.
Honest expectation: a hiring manager will probably look at this on a 13-15" laptop. Optimize for that case; make mobile functional but not your primary design target.
Loading & Skeleton States
Three distinct loading patterns, used in different places:
1. Skeleton blocks — for initial page loads. Match the layout of the eventual content so nothing shifts.
2. Shimmer on cards — for refresh-in-place (e.g., re-fetching predictions). Card stays in place, content shimmers.
3. Spinner — only inside small action buttons during a triggered action ("Run Simulation"). Never as a primary page loader; spinners-as-page-loaders are a 2015 pattern.
Stale-while-revalidate everywhere via TanStack Query: show the previous data immediately, refetch in the background, swap when fresh. This is what "feels fast" on a real product even when the network isn't.
Empty states: every list/table has a designed empty state with a one-liner explaining why and (when relevant) a CTA ("No predictions yet — the next tournament begins Thursday").
Error states: every async boundary has an error UI with a retry button. Never a raw exception. This is table stakes for a "production-quality" claim.
UX Polish Details
The small things that compound:
* Keyboard shortcuts with a ? overlay (g d → go to dashboard, g t → tournaments, / → search). Power-user features signal product maturity.
* Command palette (cmd+K) for fuzzy navigation across players, tournaments, courses. Use cmdk.
* Tooltips on every probability. Hovering a "12.4%" win probability shows the implied odds, the model's confidence interval, and the closest book line. Stats nerds will love this.
* Tabular numerics everywhere. I mentioned this; emphasizing again because it matters that much.
* Subtle borders, not heavy ones. Borders are a tell. Use 1px borders at low opacity (e.g., rgba(255,255,255,0.06)) rather than border-gray-700 — much more refined.
* Generous use of text-tertiary for labels and metadata. Hierarchy through opacity, not size.
* A favicon and OG image that match the brand. People do open multi-tab; a generic favicon undermines the polish.
* The 404 page is designed. It's a small thing that recruiters notice.

4. Deployment & Infrastructure Design
Sizing the Solution
For your stated goal — "polished but practical, professional engineering decisions over enterprise complexity" — the right shape is:
* One small VPS or PaaS instance for the API + worker
* Managed Postgres (don't self-host the database)
* Managed Redis
* Static frontend on a CDN
* Object storage for model artifacts
* Total monthly cost target: $20-40
Recommended Stack
Layer	Choice	Cost (approx)	Why
Frontend hosting	Vercel (or Cloudflare Pages)	Free tier	Best-in-class for Next.js/React, edge network, instant deploys
Backend hosting	Fly.io (or Railway)	$5-15/mo	Multi-region capable, supports persistent processes, Docker-native, great DX
Database	Neon or Supabase (Postgres)	Free tier → $19/mo	Managed, branching support useful for migrations, generous free tier
Redis	Upstash	Free tier	Serverless Redis, pay-per-request, no idle cost
Object storage	Cloudflare R2	Pennies	S3-compatible, zero egress fees — model artifacts go here
Background worker	Fly.io machine (separate process group)	included in Fly	Runs the arq worker and Prefect flows
DNS / certs	Cloudflare	Free	Standard
Error tracking	Sentry	Free tier	5k errors/month free, easily enough
Logs / metrics	Better Stack or Axiom	Free tier	Structured logging + dashboards
Uptime monitoring	Better Stack uptime	Free	Pings /healthz
The discipline here is: every line item is either free or under $20/month. Total cost stays under $40/month even with full usage. This is "polished but practical" — and it's defensible in an interview as a deliberate cost-conscious architecture.
Topology Diagram

```
                                  ┌──────────────────┐
                                  │   User Browser   │
                                  └────────┬─────────┘
                                           │
                                  ┌────────▼─────────┐
                                  │   Cloudflare     │
                                  │  (DNS + WAF)     │
                                  └──┬───────────┬───┘
                                     │           │
                                     ▼           ▼
                          ┌─────────────┐   ┌──────────────┐
                          │   Vercel    │   │   Fly.io     │
                          │  (React)    │   │  (FastAPI    │
                          │             │   │   + Worker)  │
                          │  CDN edges  │   │              │
                          └─────────────┘   └──┬────────┬──┘
                                               │        │
                                  ┌────────────┘        └───────┐
                                  │                             │
                                  ▼                             ▼
                          ┌──────────────┐              ┌──────────────┐
                          │    Neon      │              │   Upstash    │
                          │ (Postgres)   │              │   (Redis)    │
                          └──────────────┘              └──────────────┘
                                  │
                                  ▼
                          ┌──────────────┐
                          │ Cloudflare R2│
                          │  (artifacts) │
                          └──────────────┘

                          ┌─────────────────────────────────┐
                          │       Sentry / Axiom            │
                          │  (errors + structured logs)     │
                          └─────────────────────────────────┘
                                       ▲
                                       │ (all services emit here)
```
Process Architecture on Fly.io
Single app, multiple process groups (Fly.io's [processes] block):

```
[processes]
  api    = "uvicorn app.main:app --host 0.0.0.0 --port 8080"
  worker = "arq app.worker.WorkerSettings"
  flows  = "python -m app.pipelines.runner"
```
* api: 2 small machines (256MB each), behind Fly's load balancer
* worker: 1 machine (512MB), handles simulation jobs
* flows: 1 small machine, runs Prefect flows on schedule
All three share the same Docker image. Different entrypoints. This is a clean monorepo-to-multi-process deployment pattern.
Configuration & Secrets
* All config via environment variables (12-factor)
* Secrets via fly secrets set ... for backend, Vercel env vars for frontend
* .env.example checked into repo with documented defaults
* Never any real secret in the repo. A pre-commit hook (gitleaks or detect-secrets) makes this enforceable.
Database Migrations
Alembic with the following discipline:
* Every migration is reviewed before merge
* Migrations are forward-only in production (no downgrade() is run in prod; it's there for local dev only)
* Migration tested against a Neon branch before merging
* Migration runs as a Fly.io release command before the new image takes traffic
This last point is the senior signal: explain in your README that you've configured migrations to run during the release phase rather than at app startup. Startup-time migrations are a common antipattern that causes ugly failure modes during deploys.

5. CI/CD Strategy
Pipeline Shape

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitHub Actions                                │
│                                                                      │
│  on: pull_request          on: push to main         on: tag         │
│  ┌──────────────────┐      ┌──────────────────┐    ┌────────────┐   │
│  │  Quality Checks  │      │  Build & Deploy  │    │  Release   │   │
│  │  ──────────────  │      │  ──────────────  │    │  ────────  │   │
│  │  Lint (ruff)     │      │  Run all PR jobs │    │  Tag, draft│   │
│  │  Type (mypy +    │      │  Build Docker    │    │  release   │   │
│  │    tsc)          │      │  Push to ghcr.io │    │  notes     │   │
│  │  Test (pytest +  │      │  Migrate DB      │    └────────────┘   │
│  │    vitest)       │      │  Deploy Fly.io   │                     │
│  │  Contract tests  │      │  Deploy Vercel   │                     │
│  │  Calibration     │      │  Smoke test      │                     │
│  │  Frontend build  │      │  Notify Sentry   │                     │
│  └──────────────────┘      └──────────────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
```
Test Pyramid
Layer	Tool	Scope	Speed
Unit	pytest, vitest	Pure functions, components in isolation	Fast (<5s total)
Integration	pytest with real Postgres (Docker-in-CI)	Repositories, service layer	Medium
Contract	pytest, parameterized over providers	DataProvider implementations	Medium
Calibration	pytest with statistical assertions	Mock data quality	Medium
End-to-end	Playwright	Critical user paths only	Slow (1-2min)
E2E tests cover three flows: dashboard loads with predictions, simulation runs end-to-end, betting edges render. Not exhaustive — just enough to catch a broken deploy.
Deploy Discipline
* Every merge to main deploys automatically
* Failed health checks roll back automatically (Fly.io does this with release_command + [checks])
* No manual production deploys — but a manual rollback command is documented in the runbook
* Schema migrations gated on a separate migrate job that must succeed before app deploy
Conventional Commits + Changesets
Use Conventional Commits (feat:, fix:, chore:, etc.). Generate a CHANGELOG.md automatically. This is one of those small signals that you've worked on real teams.

6. Observability, Logging, & Error Tracking
The Three Pillars
1. Structured logging — every log line is JSON, with consistent fields:

```json
{
  "timestamp": "2026-05-26T14:00:00Z",
  "level": "INFO",
  "service": "api",
  "trace_id": "...",
  "event": "prediction_served",
  "tournament_id": 14,
  "model_version": "v3.2",
  "duration_ms": 47
}
```
Use structlog (Python) and pino (if you have any Node code). Ship to Axiom or Better Stack. Make the dashboard query-able by event type and trace_id.
2. Metrics — Prometheus-style metrics exposed at /metrics:
* Request rate, error rate, latency histograms per endpoint
* Prediction generation duration
* Simulation duration and iterations per second
* DataGolf API call counts and rate-limit tokens remaining
* Cache hit rates
3. Error tracking — Sentry, with releases tagged to git SHA. Errors are linked to the deploy that introduced them. Source maps uploaded for the frontend. The Sentry "release health" view shows which version has issues.
What to Instrument Beyond the Basics
The non-obvious instrumentation that signals maturity:
* Model prediction calibration drift detection. A daily job computes the Brier score on the previous week's completed events and emits a metric. An alert fires if it crosses a threshold. This is "MLOps" in the legitimate sense.
* Data freshness gauges. A gauge for "minutes since last successful DataGolf sync." Alerts when it crosses 90 minutes during active tournament hours.
* Pipeline success/failure counters. Per-flow. The dashboard shows weekly success rate.
* Trace IDs propagated through async jobs. When the simulation worker logs, it includes the trace_id from the API request that triggered it. Debugging across the async boundary is a known pain point and propagated trace IDs fix it.
Runbook
A RUNBOOK.md in the repo documents:
* How to roll back a deploy
* How to re-run a failed pipeline
* How to invalidate the prediction cache
* How to manually backfill historical data
* Common error scenarios and their fixes
Almost no portfolio projects have a runbook. It's a small file. It signals operational seriousness more than almost any other artifact.

7. Portfolio Optimization Strategy
What Hiring Audiences Actually Look For
Let me be concrete about the four audiences you're targeting and what each one cares about.
ML Engineering teams (most general SWE+ML roles): They want to see that you understand the full lifecycle, not just training a model. The artifacts they value:
* Training/serving feature consistency (your features/ module addresses this)
* Model versioning and registry (your model_versions table)
* Calibration as a first-class concern (the calibration page, isotonic regression step)
* Reproducibility (seeded simulations, deterministic mock data)
* Monitoring / drift detection (the calibration drift alert)
These are the things ML platform engineers fight for in their day jobs, and most candidates don't even know they exist. The fact that you built them — even at small scale — is a massive signal.
Sports analytics teams (DraftKings, FanDuel, PGA Tour itself, ESPN, athletic departments): They care about domain understanding and rigorous probabilistic thinking. The artifacts they value:
* The skill-and-simulate architecture (instead of one-model-per-outcome)
* Strokes-gained as the core feature framework
* Field strength adjustment in skill estimates
* Round-to-round correlation in the simulator
* DataGolf benchmark page (signals you respect prior art)
Domain knowledge is the wedge here. Any team in this space will immediately know whether you "speak golf" or whether you've just slapped golf data on a generic ML template. The depth of domain features in the project answers that question favorably.
Quant / trading teams (hedge funds, sportsbooks, prop shops): They care about probabilistic calibration, edge analysis, and bet sizing. The artifacts they value:
* Calibration plots and Brier scores (calibration > accuracy)
* Edge calculations vs. multiple books
* Kelly sizing
* Backtest framework against historical odds
* Bias-variance discussion in the methodology page
A quant interviewer will probe whether you understand why log-loss matters more than accuracy, and whether you understand that you're not betting against the model — you're betting against the market's probabilities. The methodology page is where you demonstrate this understanding.
ML Engineering teams at larger orgs (Google, Meta, Anthropic, etc.): They care about system design and engineering taste. The artifacts they value:
* The DataProvider abstraction
* The async job + SSE pattern
* The vectorized simulation engine
* Materialized views and indexing strategy
* CI/CD with release-time migrations
* Observability and runbooks
For this audience, the engineering substance might matter more than the ML substance. The README and the GitHub repo are doing most of the work.
The Hiring-Manager Lens — What Tells the Story
A senior engineer or hiring manager who's reviewing your project will spend 5-15 minutes on it, if the first 30 seconds convince them to. The funnel:
1. The README's first screen — this is your hook (covered in section 8 below)
2. The live demo URL — does the site load? Does it look good?
3. A specific cool thing they click on — this is what they remember
4. Maybe browse 2-3 files in the repo — usually README.md, architecture/ if it exists, and one source file in their area of interest
You optimize the funnel by:
* Making the README excellent
* Making the demo load fast and look immediately impressive
* Having clear "headline moments" they can click into (simulation streaming, model vs. DataGolf, custom viz)
* Having clean, well-organized code in the areas they're likely to browse
Positioning Within the Project
Three project-level positioning moves:
Position #1: "I built a model that competes with DataGolf." The DataGolf benchmark page is the proof. Even if you finish 10% behind on Brier score, the framing is "I built an independent model and benchmarked it head-to-head against one of the leading public models in the space." That's a confident, falsifiable, impressive claim.
Position #2: "I built production ML infrastructure, not a notebook." The README's architecture diagram, the CI/CD pipeline, the model registry, the calibration drift detection — these collectively prove this isn't a Kaggle project. The runbook is the cherry on top.
Position #3: "I have engineering taste." The custom D3 visualization, the dark-theme design quality, the keyboard shortcuts, the tabular numerics — taken together, these say "this person cares about the work and pays attention to detail." That's not always provable, and when it is, it's enormously valuable.

8. GitHub Presentation Strategy
The README — Structured for Impact
Open the README assuming the reader has 30 seconds. Front-load the impact:

```markdown
# PGA Tour Analytics Platform

> Production-grade ML platform for PGA Tour outcome prediction, 
> Monte Carlo simulation, and betting edge analysis. Built end-to-end: 
> data ingestion → feature engineering → gradient-boosted models → 
> 10,000-iteration tournament simulation → calibrated probabilities → 
> +EV bet identification.

**[Live Demo](https://...)** · **[Loom Walkthrough (4 min)](https://...)** · **[Methodology](https://.../methodology)**

![Hero screenshot of the dashboard]

## Highlights
- 🎯 **Calibrated probabilistic predictions** for win, T5, T10, and make-cut
- 🎲 **Vectorized Monte Carlo simulator** — 10,000 iterations of a 156-player field in ~20s
- 💰 **Betting edge analysis** across 11 sportsbooks with fractional Kelly sizing
- 📊 **Live model comparison vs. DataGolf** — head-to-head Brier scores on common events
- 🏗️ **Production-grade architecture** — pluggable data providers, async pipeline, model registry, calibration drift monitoring

## Quick Start
docker compose up   # full stack runs locally in ~60s

## Architecture
[diagram]

## Live Demo
[3-4 annotated screenshots highlighting the best moments]

## Technical Deep Dives
- [Model architecture and calibration](./docs/modeling.md)
- [Simulation engine design](./docs/simulation.md)
- [Feature engineering pipeline](./docs/features.md)
- [DataGolf integration layer](./docs/data-providers.md)

## Tech Stack
[badge row + brief explanation of major choices]

## Project Structure
[folder tree with one-line annotations]
```
The Loom Video
A 4-minute Loom walkthrough where you (on camera, or just voice + screen) demo the live app and call out the engineering moments. Most candidates skip this. Including it dramatically increases engagement.
Structure:
* 0:00-0:30: What it is, the elevator pitch
* 0:30-2:00: Live demo of the dashboard, predictions, simulation streaming, betting edges
* 2:00-3:30: A quick tour of the architecture, model lab, calibration page
* 3:30-4:00: Tech stack and what you'd build next
Folder Structure That Reads Well
Make the top-level structure scannable in 5 seconds:

```
.
├── backend/                 # FastAPI + ML + pipelines (Python)
├── frontend/                # React + TypeScript dashboard
├── pipelines/               # Prefect flows
├── infra/                   # Dockerfiles, Fly.io config, GitHub Actions
├── docs/                    # Deep-dive docs (architecture, modeling, etc.)
├── notebooks/               # Exploratory analysis (kept tidy)
├── docker-compose.yml
├── Makefile                 # Common commands
├── RUNBOOK.md
└── README.md
```
A Makefile with make dev, make test, make mock-data, make backfill is a small thing that signals operational thinking. Recruiters notice.
Commit Hygiene
Conventional commits, no wip or fixes commits on main, descriptive PR titles. Branch-and-PR workflow even though you're solo — your git log becomes a portfolio asset. A reviewer browsing the commit history sees a clean, intentional progression. Squash-merge to main keeps the history tidy.
Issues & Projects Board
Keep a Projects board with:
* A small backlog of "if I had more time" items
* A "completed" column showing what shipped
* A milestone view aligned with your phases
This makes the project feel alive and ongoing rather than static. Recruiters definitely notice the difference between a one-shot project and an actively-managed one.
License & Citation
MIT license. A CITATION.cff file in case anyone wants to reference the project (overkill, but signals seriousness). Acknowledge DataGolf as the data source. Always credit your inputs.
