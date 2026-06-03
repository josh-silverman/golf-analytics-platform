02-technical-core.md


PGA Tour Analytics Platform — Technical Core Design
Now we get into the parts that actually make or break the project. The previous document was about positioning and structure; this one is about the engineering substance that a senior interviewer will probe. I'll be explicit about tradeoffs and call out the decisions that look senior versus the ones that look junior, because that distinction is the whole point.

1. Database Schema Design
Design Philosophy
Three principles guide every table decision:
1. The schema reflects the domain, not the model. Tables represent real golf concepts — players, tournaments, rounds, shots — not ML feature vectors. Features are derived, never stored as the primary representation. This matters because when DataGolf data arrives, it'll map naturally to domain tables; if you'd built feature-shaped tables, you'd be doing a migration.
2. Immutable facts, mutable predictions. Round scores happened — they don't change. Predictions are versioned and superseded. The schema enforces this distinction.
3. Time is a first-class citizen. Every prediction, every feature snapshot, every model artifact is timestamped, because the most damaging bug in sports ML is accidentally training on future information (leakage). Schema-level timestamps make leakage detectable in queries.
Entity Relationship Diagram

```
┌──────────────┐       ┌──────────────┐       ┌─────────────────┐
│   players    │       │   courses    │       │   tournaments   │
│──────────────│       │──────────────│       │─────────────────│
│ id (PK)      │       │ id (PK)      │◄──────│ course_id (FK)  │
│ dg_id        │       │ name         │       │ id (PK)         │
│ full_name    │       │ location     │       │ name            │
│ country      │       │ par          │       │ start_date      │
│ dob          │       │ yardage      │       │ end_date        │
│ turned_pro   │       │ course_type  │       │ purse           │
│ ...          │       │ avg_score    │       │ field_strength  │
└──────┬───────┘       └──────────────┘       │ status          │
       │                                       └────────┬────────┘
       │                                                │
       │       ┌────────────────────────────────────────┘
       │       │
       ▼       ▼
┌────────────────────────┐
│  tournament_entries    │      ┌──────────────────────────┐
│────────────────────────│      │        rounds            │
│ id (PK)                │◄─────│──────────────────────────│
│ tournament_id (FK)     │      │ id (PK)                  │
│ player_id (FK)         │      │ entry_id (FK)            │
│ status (active|cut|wd) │      │ round_number (1-4)       │
│ final_position         │      │ score                    │
│ final_score_to_par     │      │ score_to_par             │
│ official_money         │      │ tee_time                 │
└──────┬─────────────────┘      │ weather_snapshot_id (FK) │
       │                        │ sg_off_the_tee           │
       │                        │ sg_approach              │
       │                        │ sg_around_green          │
       │                        │ sg_putting               │
       │                        │ sg_total                 │
       │                        │ driving_distance_avg     │
       │                        │ fairways_hit             │
       │                        │ gir                      │
       │                        │ putts                    │
       │                        └───────────┬──────────────┘
       │                                    │
       │                                    ▼
       │                       ┌─────────────────────────┐
       │                       │       shots             │
       │                       │─────────────────────────│
       │                       │ id (PK)                 │
       │                       │ round_id (FK)           │
       │                       │ hole_number             │
       │                       │ shot_number             │
       │                       │ from_location           │
       │                       │ to_location             │
       │                       │ distance_to_pin_before  │
       │                       │ distance_to_pin_after   │
       │                       │ strokes_gained          │
       │                       └─────────────────────────┘
       │
       ▼
┌──────────────────────────┐       ┌─────────────────────────────┐
│ player_skill_snapshots   │       │   predictions               │
│──────────────────────────│       │─────────────────────────────│
│ id (PK)                  │       │ id (PK)                     │
│ player_id (FK)           │       │ tournament_id (FK)          │
│ as_of_date               │       │ player_id (FK)              │
│ sg_ott_rating            │       │ model_version_id (FK)       │
│ sg_app_rating            │       │ generated_at                │
│ sg_arg_rating            │       │ win_prob                    │
│ sg_putt_rating           │       │ top5_prob                   │
│ overall_rating           │       │ top10_prob                  │
│ form_index               │       │ make_cut_prob               │
│ rating_variance          │       │ expected_finish             │
└──────────────────────────┘       │ expected_score              │
                                   └──────────────┬──────────────┘
                                                  │
                                                  ▼
                                   ┌─────────────────────────────┐
                                   │   simulation_runs           │
                                   │─────────────────────────────│
                                   │ id (PK)                     │
                                   │ tournament_id (FK)          │
                                   │ model_version_id (FK)       │
                                   │ n_iterations                │
                                   │ random_seed                 │
                                   │ started_at, completed_at    │
                                   │ status                      │
                                   └──────────────┬──────────────┘
                                                  │
                                                  ▼
                                   ┌─────────────────────────────┐
                                   │ simulation_results          │
                                   │─────────────────────────────│
                                   │ run_id (FK)                 │
                                   │ player_id (FK)              │
                                   │ finish_position_distribution│  (JSONB array)
                                   │ score_distribution          │  (JSONB array)
                                   │ wins, top5s, top10s, cuts   │
                                   └─────────────────────────────┘

┌──────────────────────────┐       ┌─────────────────────────────┐
│   model_versions         │       │   betting_lines             │
│──────────────────────────│       │─────────────────────────────│
│ id (PK)                  │       │ id (PK)                     │
│ name                     │       │ tournament_id (FK)          │
│ model_type (xgb|lgbm)    │       │ player_id (FK)              │
│ trained_at               │       │ book_name                   │
│ training_data_through    │       │ market (win|top5|top10|cut) │
│ artifact_path            │       │ decimal_odds                │
│ feature_set_hash         │       │ implied_prob                │
│ metrics (JSONB)          │       │ captured_at                 │
│ is_active                │       └─────────────────────────────┘
└──────────────────────────┘
```
Key Design Decisions Worth Discussing in an Interview
Why a separate tournament_entries table? Because the player-tournament relationship has its own attributes (final position, cut status, money earned) that belong neither to the player nor the tournament. Embedding these on rounds would create the wrong cardinality — a player has one entry but up to four rounds. This is textbook relational modeling and a hiring manager will notice if you got it wrong.
Why player_skill_snapshots as a separate table? This is the "as-of-date" pattern, and it's the single most important thing that prevents data leakage. When you generate features for predicting Tournament X starting on date D, you query skill snapshots WHERE as_of_date < D. The database physically prevents you from accidentally using future information. Without this, a junior version of this schema would just have a players.current_rating column that gets overwritten — and your "model" would silently train on data from the future. Mentioning this design choice in your README signals real ML engineering maturity.
Why store strokes_gained on rounds AND shots? Redundant on purpose. Round-level SG is the queryable aggregate the dashboard hits constantly; shot-level SG is the source-of-truth granularity that supports the custom visualizations. The aggregate is computed from the granular data during ingestion, never re-derived at query time. This is a deliberate denormalization, and you should be ready to justify it as a read-optimization with a clear refresh story.
Why predictions and simulation_results are separate. Predictions are the direct model outputs (the calibrated probabilities); simulation results are the aggregated MC outputs (distributions, counts). They're conceptually different artifacts produced by different stages of the pipeline, and conflating them obscures which stage produced a given number — which matters for debugging probabilities that look wrong.
JSONB for distributions. PostgreSQL's JSONB is the right call for the score and finishing-position distributions because they're variable-length, queried as a whole (not field-by-field), and have a natural array shape. Don't normalize this into a simulation_result_buckets child table — that would be over-normalization for data you always read together.
Indexing Strategy
Three categories of indexes, each with a purpose:
Index	Purpose	Reasoning
(tournament_id, player_id) on tournament_entries	The dashboard's most common join key	Composite covers the common access pattern
(player_id, as_of_date DESC) on player_skill_snapshots	Point-in-time skill lookups during feature engineering	DESC because you almost always want "most recent before date X"
(tournament_id, generated_at DESC) on predictions	"Latest predictions for this tournament"	Same logic
Partial index WHERE is_active = true on model_versions	The active-model lookup is hot	Tiny index, big win
Don't index everything; over-indexing on a portfolio project is just as much of a red flag as under-indexing. Justify each one.
Materialized Views for Analytics

```sql
-- Conceptual, not for execution
player_form_rolling_20    -- 20-round rolling SG averages per player
course_player_history     -- Player performance at each course historically
field_strength_history    -- Computed field strength for each completed tournament
prediction_calibration    -- Reliability bins for model evaluation
```
Refresh schedule: CONCURRENTLY after each tournament's completion event, not on a fixed cron. Drive refreshes off domain events, not the clock.

2. Data Pipeline Architecture
Why This Section Matters Most
If I'm a hiring manager looking at this project, the data pipeline is where I figure out whether you're an ML practitioner or an ML engineer. Anyone can train a model in a notebook. Building the pipeline that gets data in, transforms it correctly, retrains on a schedule, and serves features consistently in production is the actual job.
Orchestration Choice: Prefect
Pick Prefect over Airflow for this project. Reasoning: Airflow is the more "enterprise" answer and probably what a Fortune 500 shop uses, but it has heavy infrastructure overhead (scheduler, webserver, metadata DB) that's overkill for a single-machine portfolio deployment. Prefect 2.x runs as a single Python process, has a much cleaner Pythonic API, and the resulting code reads better in a code review. The right framing in an interview: "For a system at this scale Prefect was the proportionate choice; for a 500-DAG analytics team I'd reach for Airflow or Dagster." That framing — picking the right tool for the scale and naming the alternatives — is the senior signal.
Pipeline Topology

```
                     ┌──────────────────────┐
                     │   Trigger Sources    │
                     │ - cron (daily 6am)   │
                     │ - event (tourn end)  │
                     │ - manual (CLI)       │
                     └──────────┬───────────┘
                                │
                                ▼
              ┌─────────────────────────────────┐
              │  Orchestrator (Prefect Flows)   │
              └─────────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
       ┌────────────┐    ┌────────────┐    ┌────────────┐
       │ Ingestion  │    │  Feature   │    │  Training  │
       │   Flow     │───▶│   Build    │───▶│    Flow    │
       │            │    │   Flow     │    │            │
       └────────────┘    └────────────┘    └─────┬──────┘
              │                                  │
              │                                  ▼
              │                          ┌────────────────┐
              │                          │  Calibration   │
              │                          │  & Validation  │
              │                          └────────┬───────┘
              │                                   │
              │                                   ▼
              │                          ┌────────────────┐
              │                          │ Model Registry │
              │                          │   (promote)    │
              │                          └────────┬───────┘
              │                                   │
              ▼                                   ▼
       ┌──────────────────────────────────────────────┐
       │             Postgres (canonical)              │
       └──────────────────────────────────────────────┘
                                ▲
                                │
              ┌─────────────────┴─────────────────┐
              │  Simulation Flow (on demand)      │
              │  - triggered after each training  │
              │  - re-run per round during tourn  │
              └────────────────────────────────────┘
```
Five Distinct Flows, Each With One Job
Flow	Trigger	Inputs	Outputs	SLA
Ingestion	Daily cron + manual	DataProvider	New rows in tournaments, rounds, shots	<5 min
Feature Build	After successful ingestion	Postgres tables	player_skill_snapshots rows	<10 min
Training	After feature build, if new tournament completed	Feature snapshots	New model_versions row, artifact file	<30 min
Simulation	After training + on demand for upcoming tournaments	Model artifact + entry list	simulation_runs + simulation_results	<2 min for 10k iters
Prediction Materialization	After simulation	Simulation outputs	predictions rows	<1 min
The dependencies form a clean DAG, and each flow is independently runnable. That last property is critical. If the simulation flow has a bug, you fix it and re-run just simulation without re-ingesting and re-training. Pipelines that don't support partial re-runs cause real operational pain, and an interviewer who's been on call will absolutely ask about this.
Idempotency and Backfills
Every flow is idempotent. Concretely:
* Ingestion uses INSERT ... ON CONFLICT DO UPDATE keyed on natural business IDs (DataGolf's tournament/player IDs), never on synthetic surrogate keys
* Feature builds are keyed on (player_id, as_of_date) — re-running for the same date overwrites cleanly
* Training writes new model_versions rows with a unique hash of (training data through date, feature set hash, hyperparameters), so re-running the same training is a no-op or produces an identical artifact
Backfills are just "run flow for date range D1 to D2." If your pipeline can't backfill, it isn't a real pipeline.
Failure Handling
Three failure modes, three responses:
1. Transient (network, rate limit): Prefect retry with exponential backoff, max 5 attempts
2. Data quality (validation failure): Fail loud, write a row to a pipeline_errors table, alert via log, do not write bad data downstream
3. Schema (upstream shape changed): Fail at the adapter layer — this is the whole point of having a DataProvider abstraction — and surface a clear error
Talk about #2 explicitly in your README. The discipline of failing loud on data quality issues rather than silently writing nulls is one of the most under-appreciated things in ML pipelines.

3. Feature Engineering System
Design Philosophy
The single most important property of a feature pipeline is identical computation in training and inference. The way to enforce this is to have one place where features are defined, called from both paths. I mentioned this in the previous document; here's how it actually shapes the code organization.

```
backend/features/
├── __init__.py
├── base.py                  # Feature, FeatureSet, FeatureRegistry classes
├── primitives/              # Low-level reusable calculations
│   ├── strokes_gained.py
│   ├── rolling.py
│   ├── decay.py
│   └── normalization.py
├── player/                  # Player-centric features
│   ├── form.py              # recent form indices
│   ├── skill.py             # latent skill estimates
│   └── consistency.py       # variance-based features
├── course/                  # Course-centric features
│   ├── fit.py               # player-course fit
│   └── history.py           # historical performance
├── field/                   # Tournament-context features
│   ├── strength.py
│   └── conditions.py
├── feature_sets/            # Named, versioned feature compositions
│   ├── v1_baseline.py
│   └── v2_extended.py
└── pipeline.py              # Orchestrates feature computation
```
The Feature Abstraction
Every feature is a pure function with a typed signature and a declared dependency on upstream data. Conceptually:

```
Feature:
    name: str
    version: int
    depends_on: [str]  # other features or raw tables
    compute(player_id, as_of_date, context) -> float | dict
```
Why this matters: a FeatureRegistry can compute the dependency graph and execute features in the right order, cache intermediate results, and produce a deterministic hash of "the entire feature set as of this version" — which goes into model_versions.feature_set_hash. Now you can answer the question "is this prediction stale because the feature definitions changed?" with a single column comparison. Senior ML engineers will love this.
Feature Categories With Concrete Examples
Strokes Gained Skill Estimates — these are the foundation. Approximation of how this works:

```
sg_app_rating(player, as_of_date) =
    weighted_average(
        player's SG:APP per round,
        weights = exp(-decay_rate * days_ago) * field_strength_adjustment
    )
```
The two non-obvious pieces:
* Field strength adjustment: a 70.5 SG round at the Players Championship is harder than a 70.5 round at a fall opposite-field event. Multiply by a per-tournament field strength factor before averaging.
* Time decay: a round from 6 months ago should count less than a round from last week. Exponential decay with a half-life of ~60-90 days is the standard.
Form Index — a player's recent performance relative to their baseline:

```
form_index(player, as_of_date) =
    rolling_mean(sg_total, last_8_rounds) - long_run_mean(sg_total, last_50_rounds)
```
Positive means heating up, negative means cooling. This is one number that turns out to be quite predictive and is the kind of domain-aware feature that signals you actually understand golf.
Course Fit — player's historical SG categories vs. the course's demands:

```
course_fit(player, course) =
    dot_product(
        player_sg_profile = [sg_ott, sg_app, sg_arg, sg_putt],
        course_sg_demands = [importance_ott, importance_app, ...]
    )
```
Course demand weights come from analyzing which SG categories correlate with winning at that course historically. A long course with thick rough weights SG:OTT and SG:APP heavily; a short course with fast greens weights SG:ARG and SG:PUTT.
Course History — a player's actual past results at this specific course, with regression to the mean to handle small samples:

```
course_history(player, course) =
    regress_to_mean(
        observed = mean(player's past SG at this course),
        prior = player's overall SG average,
        n_samples = rounds_played_at_course,
        regression_strength = f(small_sample_penalty)
    )
```
The empirical Bayes regression-to-the-mean step is what separates this from naive "Tiger plays well at Augusta" handwaving.
Field Strength — a property of the tournament, used both as a feature and as the adjustment factor for skill ratings:

```
field_strength(tournament) =
    mean(overall_rating of all players in field, weighted by OWGR or similar)
```
Conditions / Weather — wind speed, rain, temperature. Affects all players, but affects them unequally (some players are better wind players).
The Two-Mode Execution Story

```
                    ┌──────────────────────┐
                    │  Feature Functions   │  (single source of truth)
                    └──────────┬───────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
                ▼                             ▼
    ┌────────────────────┐         ┌────────────────────┐
    │   Batch Mode       │         │   Online Mode      │
    │   (training)       │         │   (inference)      │
    │                    │         │                    │
    │  Iterates over     │         │  Computes for      │
    │  many              │         │  current field of  │
    │  (player, date)    │         │  players, today    │
    │  pairs from history│         │                    │
    └──────────┬─────────┘         └──────────┬─────────┘
               │                              │
               ▼                              ▼
    Writes to feature_           Returns to prediction
    snapshots tables             flow in-memory
```
Same functions, two callers. Training/serving skew becomes structurally impossible.

4. Simulation Engine Architecture
The Core Methodology
Here's the model in plain English. For each player in a tournament, we have:
* An estimated mean per-round score (derived from their skill rating + course + conditions)
* An estimated variance (some players are more consistent than others)
* Correlations across rounds (a player playing well in round 1 raises round 2 expectations slightly)
The simulation does the following 10,000 times:
1. For each player, sample a round 1 score from their personalized distribution
2. Apply the cut after round 2 (top 65 + ties, typically)
3. For surviving players, sample rounds 3 and 4
4. Rank all players to determine finishing positions
5. Record: did this player win? finish T5? T10? make the cut?
Aggregating across iterations gives the calibrated probabilities. The math is conceptually simple; the engineering is where it gets interesting.
Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    SimulationEngine                         │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌─────────────────────┐    ┌──────────────────────────┐  │
│  │  PlayerScoreModel   │    │  TournamentSimulator     │  │
│  │  ─────────────────  │    │  ──────────────────────  │  │
│  │  Given player +     │    │  Orchestrates one full   │  │
│  │  context, returns   │    │  4-round tournament      │  │
│  │  score distribution │    │  including cut logic     │  │
│  └─────────┬───────────┘    └────────────┬─────────────┘  │
│            │                              │                │
│            └──────────────┬───────────────┘                │
│                           ▼                                │
│              ┌───────────────────────────┐                 │
│              │   IterationRunner         │                 │
│              │   ─────────────────       │                 │
│              │   - Vectorized over       │                 │
│              │     iterations (NumPy)    │                 │
│              │   - Manages RNG state     │                 │
│              │   - Yields completed sims │                 │
│              └─────────────┬─────────────┘                 │
│                            │                               │
│                            ▼                               │
│              ┌───────────────────────────┐                 │
│              │   ResultAggregator        │                 │
│              │   ─────────────────       │                 │
│              │   Win counts, T5/T10,     │                 │
│              │   cut rates, score dists  │                 │
│              └─────────────┬─────────────┘                 │
│                            │                               │
└────────────────────────────┼───────────────────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ simulation_results   │
                  │   (Postgres)         │
                  └──────────────────────┘
```
The Vectorization Decision
The naive approach is for iteration in 10_000: for player in 156: for round in 4: sample(). That's ~6M Python loop iterations and will take minutes.
The right approach is to vectorize over iterations: sample a (10_000, 156) matrix of round 1 scores in one NumPy call. Cut logic becomes a boolean mask. Round 2 is another (10_000, 156) matrix with masked entries. Total simulation: well under 30 seconds for 10k iterations.
This is one of those things where the right answer is technically straightforward but signals significant experience: anyone who's done real Monte Carlo work in Python knows this; people who've only done it in notebooks usually don't. Call this out explicitly in your README: "Simulation is vectorized over iterations using NumPy; 10,000 iterations of a 156-player field completes in ~20 seconds on a single core."
Score Distribution Model
For each (player, round) we need a distribution. Two reasonable choices:
Approach	Pros	Cons
Normal distribution with predicted mean and variance	Simple, fast, easy to correlate	Symmetric — golf scores are slightly right-skewed (more blowups than miracles)
Skew-normal or mixture of normals	More realistic, handles tail behavior	More parameters to estimate, slower sampling
Recommendation: start with Normal, document the limitation, upgrade to skew-normal in a v2 if time allows. A hiring manager will be satisfied by "I chose Normal initially, validated calibration against historical results, and identified upgrading to skew-normal as the next iteration." That's much better than "I used a fancy distribution but my calibration was terrible because I overfit."
Correlation Structure
A common naïve mistake: simulating each round independently. In reality, a player playing well in round 1 is more likely to play well in round 2 (because they're "on" that week — pin sheets are similar, course knowledge accumulates, confidence). Round-to-round correlation in PGA Tour data is around 0.2-0.3.
Model this with a multivariate normal at the player level: each player's 4 rounds are drawn from a 4D normal with off-diagonal correlation. The math is clean and the realism boost is meaningful.
You can also add a tournament-wide "scoring conditions" factor — if it's windy on Thursday, everyone scores worse — by sampling a shared shock that gets added to all players' round 1 scores. This is the kind of detail that shows you really thought about it.
Reproducibility
Every simulation run records its random seed. Same seed + same model version + same field = identical results. This sounds obvious but a surprising number of ML systems don't enforce it, and an interviewer who's debugged a non-reproducible simulation will absolutely ask about it.
Streaming Mode vs. Batch Mode
The simulation engine should support two modes:
* Batch: run all 10k iterations, then aggregate and write results
* Streaming: yield aggregate stats every N iterations, so the frontend can show "live updating" probabilities as the sim progresses
Implementing streaming via Server-Sent Events from the API to the frontend is a flashy demo feature that's not hard once the engine is structured properly. Worth doing in Phase 4 if time allows.

5. DataProvider Interface Design
Why This Is the Most Important Code in the Project
If you nail one thing architecturally, nail this. The entire system's claim to "production-ready" rests on whether you can swap data sources without touching the consumers. Every senior interviewer will look for this.
Interface Shape
The interface lives in a single file (backend/data_providers/base.py) and is the only thing the rest of the application imports. Concrete providers are loaded via dependency injection / a factory function configured from environment variables.

```
class DataProvider (abstract):

    # Reference / static-ish data
    list_players() -> List[Player]
    get_player(player_id) -> Player
    list_courses() -> List[Course]
    get_course(course_id) -> Course

    # Tournament data
    list_tournaments(season: int, status: optional) -> List[Tournament]
    get_tournament(tournament_id) -> Tournament
    get_tournament_field(tournament_id) -> List[TournamentEntry]

    # Round-level results
    get_rounds(tournament_id) -> List[Round]
    get_rounds_for_player(player_id, since: date) -> List[Round]

    # Shot-level (optional, may not be available from all sources)
    get_shots(round_id) -> List[Shot] | NotImplementedError

    # Betting (separate provider in reality, included here for completeness)
    get_betting_lines(tournament_id) -> List[BettingLine]

    # Health / metadata
    get_data_freshness() -> DataFreshness
    get_source_name() -> str
```
Critical Design Decisions
Return Pydantic domain models, not dicts. This is what makes the interface a real contract. Player, Tournament, Round etc. are Pydantic models with typed fields. The mock provider has to construct valid instances, and so does the DataGolf provider. If DataGolf's API response shape doesn't match, the adapter is responsible for the translation — never the consumer.
Async by default. All methods are async. The mock provider implements them with trivial await asyncio.sleep(0) or async generators; the DataGolf provider uses httpx.AsyncClient. This keeps the FastAPI request path fully async and doesn't require an interface change when you swap implementations.
Pagination is built into the interface from day one. Methods that could return large result sets return paginated responses or async iterators, even when the mock provider could trivially return everything. Adding pagination later requires touching every caller; building it in from the start costs nothing.
Capability declaration. Some methods may not be supported by all providers (e.g., shot-level data might not be in all DataGolf tiers). The interface includes a capabilities() -> Set[Capability] method so consumers can check what's available. Cleaner than try/except NotImplementedError scattered through the codebase.
Caching is a decorator, not built into the interface. A CachingProviderWrapper wraps any DataProvider and adds Redis-backed caching with configurable TTLs per method. This is composition over inheritance — you can stack a CachingWrapper around either the mock or the DataGolf provider without changing either. Decorator pattern, applied cleanly.

```
┌─────────────────────────────────────────────────────────┐
│                  Application Layer                       │
│         (only knows about DataProvider interface)        │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
                ┌─────────────────┐
                │  DataProvider   │  (abstract)
                └────────┬────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐    ┌─────────────┐  ┌──────────────┐
   │  Mock   │    │  DataGolf   │  │  Caching     │
   │Provider │    │  Provider   │  │  Wrapper     │  ─► wraps either
   └─────────┘    └─────────────┘  └──────────────┘
```
Configuration:

```
DATA_PROVIDER=mock     # or "datagolf"
DATA_PROVIDER_CACHE=true
DATAGOLF_API_KEY=...   # only read if provider=datagolf
```
In an interview, the entire conversation about "how would you swap data sources" becomes a 30-second answer with a clean diagram. That's the whole win.
Contract Tests
There's a tests/contract/test_dataprovider_contract.py that runs the same test suite against every provider implementation. If a provider passes the contract tests, it's a valid substitute. When DataGolf is integrated, the contract tests catch any subtle differences (e.g., DataGolf returning slightly different field names or status enums) before they reach production.
This is the kind of test design that real platform teams use. It's overkill for a portfolio project in the strict ROI sense, and worth it anyway for what it signals.

6. Mock Data Generation Strategy
Given your goal of "carefully calibrated to match realistic PGA Tour distributions," this section is meaningful. Cheap mock data would let you build the system, but the models would behave nonsensically and undermine the impressiveness of the simulations.
Calibration Targets
The mock data should match real PGA Tour distributions on these dimensions. These numbers are approximate ranges to design against, not gospel:
Quantity	Target
Mean round score on PGA Tour	~70.5 to 71.5 depending on course
Round score std dev across field	~2.5 to 3.0 strokes
Top player SG:Total vs. field average	~+2.0 strokes per round
Bottom player SG:Total	~-1.5 to -2.0 strokes per round
Cut line typically	E to +3 after 36 holes
Round-to-round correlation within a tournament	~0.2-0.3
Win probability for #1 in field	~6-12% depending on field strength
% of players who make the cut	~50% (top 65 + ties of ~156)
Driving distance: avg / range	~298 yards / 270-325
Strokes gained category correlations	SG:OTT and SG:APP positively correlated (~0.3); SG:PUTT nearly independent of long game
These are the validation targets. If your mock data produces these distributions, the models trained on it will produce believable outputs.
Generation Architecture

```
┌──────────────────────────────────────────────────────────┐
│                MockDataGenerator                         │
│                                                          │
│  Step 1: Generate player population                      │
│  ─────────────────────────────────                       │
│  - Sample ~250 players                                   │
│  - Each player has latent skills:                        │
│    sg_ott, sg_app, sg_arg, sg_putt ~ MVN with realistic  │
│    means, std devs, and inter-skill correlations         │
│  - Plus consistency factor (round variance multiplier)   │
│  - Plus career arc (peak age ~30, decline thereafter)    │
│                                                          │
│  Step 2: Generate courses                                │
│  ──────────────────────                                  │
│  - ~50 courses with par (mostly 70-72), yardage,         │
│    difficulty modifier                                   │
│  - Each course has SG-category importance weights        │
│                                                          │
│  Step 3: Generate tournament calendar                    │
│  ───────────────────────────────                         │
│  - ~5 seasons × ~45 tournaments = ~225 tournaments       │
│  - Realistic scheduling (no overlapping majors etc.)     │
│                                                          │
│  Step 4: Assign fields                                   │
│  ───────────────────                                     │
│  - Field strength varies by event type                   │
│  - Top players play majors, skip opposite-field events   │
│  - Field size ~144-156                                   │
│                                                          │
│  Step 5: Simulate tournament results forward in time     │
│  ────────────────────────────────────────────────       │
│  - Uses the SAME score-distribution logic as the         │
│    eventual simulation engine                            │
│  - Apply weekly skill drift (random walk)                │
│  - Apply form streaks (autocorrelation)                  │
│  - Compute SG categories per round                       │
│  - Apply cut after R2                                    │
│                                                          │
│  Step 6: Generate shot-level data (optional, expensive)  │
│  ────────────────────────────────────────────────       │
│  - For a subset of tournaments, generate shot-by-shot    │
│  - Use Mark Broadie's strokes-gained baselines           │
│                                                          │
└──────────────────────────────────────────────────────────┘
```
The Critical Insight: Reuse the Simulation Engine
The mock data generator should use the same scoring model as your simulation engine. Two reasons:
1. It guarantees the mock data is "in distribution" for the simulator — your simulations will look believable because they're sampling from the same kind of process that generated the training data
2. It's a forcing function: building the mock generator is partial work on the simulation engine, so you don't write the same logic twice
The difference is direction: the generator samples scores given known true skills (forward); the simulator samples scores given estimated skills (also forward, but with uncertainty). The models trained in between estimate skills from observed scores (the inverse problem). This three-way relationship is elegant and worth highlighting in your README.

```
        TRUE SKILLS                  ESTIMATED SKILLS
              │                              ▲
              │                              │
              │ Mock Generator               │ ML Model
              │ (samples scores              │ (infers skills
              │  from skills)                │  from scores)
              ▼                              │
        OBSERVED SCORES ─────────────────────┘
              │
              │ Simulator
              │ (samples future scores
              │  from estimated skills)
              ▼
        PREDICTED OUTCOMES
```
Skill Drift and Career Arcs
Static skills make for boring (and unrealistic) training data. Implement:
* Weekly random walk: each player's skills drift slightly week-over-week, std dev ~0.05 strokes
* Career arc: skills follow a peak-and-decline curve, peaking around age 28-32 for most players, with idiosyncratic variation
* Form streaks: implement via an AR(1) process on a "form" latent variable that adds to current-week skill
This produces data where rolling averages and form indices actually mean something, which is essential for the form-related features to work.
Realistic Player Names and Identities
Don't generate "Player_001". Generate ~250 plausible-looking names using a name generator, give them countries weighted by real PGA Tour demographics, and assign realistic ages. The dashboard reading "Henrik Larsson finished T7" feels real; "Player_117 finished T7" doesn't, and the demo loses impact.
Validation Suite
A separate tests/calibration/ directory that runs against generated data and checks:
* Mean score, std dev within target ranges per course type
* SG correlations within target ranges
* Cut line distribution looks plausible
* Win-percentage by skill rank looks plausible
* Round-to-round correlation is detectable
The calibration suite is itself a portfolio artifact — it shows you don't just generate mock data, you validate it against domain constraints. Include the calibration report in the README, with histograms comparing your generator output to target distributions. This is the kind of thing that takes a project from "interesting" to "genuinely impressive."
Deterministic Seeding
The entire mock dataset is generated from a single root seed. Anyone who clones the repo and runs make mock-data gets bit-identical data. This is huge for reproducibility and makes your models' results something an interviewer can recreate on their own laptop — which dramatically increases the chance they actually do.

Wrap-Up of This Pass
Where we stand after this document:
* Schema and pipeline are designed to a level you could actually start building from
* The feature engineering, simulation, and DataProvider designs are at the conceptual level where the abstractions are nailed down, but the concrete function signatures and implementation are still to be written
* The mock data strategy has clear calibration targets and a generation architecture
What I'd suggest tackling in the next pass:
1. DataGolf integration layer — specifically how the DataGolfProvider maps the real API surface (endpoints, response shapes, rate limits) into our interface, and what migration steps look like
2. Frontend structure — page-by-page breakdown, component hierarchy, the custom D3 visualization choices, and the polish details that make a dashboard look like a product rather than a project
3. Deployment architecture — concrete platform recommendations, CI/CD, secrets, observability, with the "polished but practical" sizing you specified
4. Portfolio optimization strategy — README structure, the Loom video, the GitHub presentation, what to highlight on a resume bullet, and how to talk about this in an interview
