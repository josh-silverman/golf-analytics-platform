01-vision-and-system-design.md

PGA Tour Analytics Platform — Architecture & Planning Document
Before diving in, a quick framing note: you asked for elite-level planning, so I'm going to be opinionated where it matters and flag tradeoffs explicitly. A hiring manager reviewing this project will care less about what you built and more about why you made specific decisions — so I'll emphasize the reasoning throughout. Let's start with the four areas you asked me to lead with, then I'll outline how we'll tackle the remaining eight in subsequent passes.

1. Product Vision
The One-Sentence Pitch
A production-grade PGA Tour analytics platform that ingests tour data, engineers strokes-gained features, trains gradient-boosted models to predict tournament outcomes, runs Monte Carlo simulations across 156-player fields, and surfaces betting edges through a polished React dashboard.
Why This Project Wins as a Portfolio Piece
Most ML portfolio projects fail in predictable ways: they're either Kaggle-flavored notebooks with no system around them, or they're CRUD apps with a model bolted on. This project sidesteps both traps because golf is genuinely hard to model, and that difficulty is legible to a technical interviewer.
Specifically, golf forces you to demonstrate:
* Hierarchical modeling intuition — players nested in fields nested in courses nested in conditions. This isn't a flat tabular problem.
* Simulation thinking — you can't just predict "winner." You have to simulate the full joint distribution of 156 players × 4 rounds, then derive win/top-5/top-10/cut probabilities as marginals.
* Probabilistic calibration — betting edge analysis is meaningless without well-calibrated probabilities, which forces you to think about isotonic regression, Brier scores, and reliability diagrams instead of just accuracy.
* Feature engineering depth — strokes gained is a rich, domain-specific feature space that lets you show you understand the sport, not just the math.
The combination of ML + simulation + betting + a real-time-ish dashboard hits four distinct competency signals that most candidates can only hit one or two of.
Target "Personas" for the Dashboard
Even though you're the only real user, designing for personas sharpens the UI decisions:
1. The Analyst — wants leaderboards, model probabilities, SG breakdowns, trend charts
2. The Bettor — wants edge calculations, expected value, Kelly sizing, line shopping comparisons
3. The Engineer (you, showing this off) — wants to see model metadata, feature importances, calibration plots, simulation traces
Designing the frontend with these three "modes" in mind prevents the dashboard from becoming a wall of undifferentiated charts.
Scope Discipline — What This Project Is NOT
This matters because a portfolio project that tries to do everything looks unfocused. We're explicitly not building:
* A live betting execution system (no broker integrations, no real money)
* A mobile app (responsive web only)
* A multi-tenant SaaS (single-user, single-deployment)
* A real-time streaming pipeline (batch with reasonable freshness is fine — golf isn't high-frequency)
* A general "sports analytics platform" (PGA Tour only — depth over breadth)

2. Core System Architecture
High-Level Topology
```
┌─────────────────────────────────────────────────────────────────┐
│                         BROWSER (React SPA)                      │
│   Dashboard │ Player Pages │ Tournament View │ Betting Edge │   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS / JSON
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                         │
│  ┌──────────────┬────────────────┬─────────────────────────┐   │
│  │ REST Routes  │ Service Layer  │  Domain Models (Pydantic)│   │
│  └──────────────┴────────────────┴─────────────────────────┘   │
└──────┬───────────────┬────────────────────┬─────────────────────┘
       │               │                    │
       ▼               ▼                    ▼
┌──────────────┐ ┌────────────┐  ┌────────────────────────────┐
│  PostgreSQL  │ │ Redis Cache│  │  Model Artifacts (MLflow   │
│ (canonical)  │ │ (hot reads)│  │  or filesystem registry)   │
└──────────────┘ └────────────┘  └────────────────────────────┘
       ▲
       │ writes
┌──────┴──────────────────────────────────────────────────────────┐
│                  Data & ML Pipeline (Prefect or Airflow)         │
│  ┌───────────┐ ┌────────────┐ ┌──────────┐ ┌────────────────┐  │
│  │ Ingestion │→│ Feature    │→│ Training │→│ Simulation     │  │
│  │ (adapter) │ │ Engineering│ │ Pipeline │ │ Engine         │  │
│  └─────┬─────┘ └────────────┘ └──────────┘ └────────────────┘  │
└────────┼─────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│   Data Source Adapter (abstract)     │
│   ┌──────────────┬─────────────────┐ │
│   │ MockProvider │ DataGolfProvider│ │  ← swap implementation, not callers
│   └──────────────┴─────────────────┘ │
└──────────────────────────────────────┘
```
The Single Most Important Architectural Decision: The Data Provider Abstraction
Since you don't have DataGolf API access yet but will eventually integrate it, the entire architecture must be built around a DataProvider interface that has at least two implementations: MockDataProvider and DataGolfProvider. Every other component — feature engineering, training, simulation, the API — depends on this interface, never on either concrete implementation.
Why this matters so much:
* It forces you to define the data contract before you have data, which is exactly what senior engineers do
* The DataGolf integration later becomes a single class to write, not a refactor
* It makes the system testable — you can run integration tests against deterministic mock data forever
* A hiring manager will immediately recognize this as the Repository / Adapter pattern applied correctly
I'll detail the interface shape when we get to section 10 (DataGolf integration layer), but treat it as the architectural keystone of the whole project.
Layering and Separation of Concerns
Four distinct layers, each with one job:
Layer	Responsibility	Talks To
Presentation (React)	Render, user interaction, client-side state	API layer only
API (FastAPI routes)	HTTP concerns, validation, auth, serialization	Service layer only
Service / Domain	Business logic, orchestration, the interesting code	Repositories, ML registry, simulation engine
Infrastructure	DB access, external APIs, file I/O, caching	Postgres, Redis, DataProvider
The rule that enforces this: lower layers never import from higher layers, and routes never import repositories directly. If a FastAPI route is doing a SQL query, the architecture is broken.
Synchronous vs. Asynchronous Boundaries
This is where a lot of portfolio projects get sloppy. Be explicit:
* Sync, request/response: dashboard reads, player lookups, leaderboard queries → FastAPI + Postgres + Redis cache
* Async, scheduled: ingestion, feature builds, model training → Prefect/Airflow DAGs
* Async, on-demand but slow: Monte Carlo simulations → background job queue (Celery or arq), results written back to Postgres, frontend polls or uses SSE
Don't try to run a 10,000-iteration tournament simulation inside a FastAPI request handler. That's a classic mistake and an easy thing for an interviewer to catch.
Caching Strategy
Redis sits between the API and Postgres for a specific, narrow purpose: caching computed model outputs and simulation results, not raw DB rows. Keys look like predictions:{tournament_id}:{model_version} with TTLs aligned to when new data could change them (e.g., expire after each round completes). This is more sophisticated than "cache everything" and shows you understand cache invalidation.

3. Major Engineering Decisions & Tradeoffs
I'll walk through the decisions that will get asked about in an interview. For each, I'll give the choice, the alternatives, and why we're picking what we're picking.
Decision 1: Monorepo vs. Split Repos
Choice: Monorepo with /backend, /frontend, /pipelines, /infra top-level directories.
Tradeoffs: Split repos give cleaner CI boundaries but add coordination overhead for a solo project. A monorepo lets you do atomic commits across the stack (e.g., "add top-5 endpoint + frontend card in one PR") which reads well in a git log a hiring manager might browse. The atomic-commit benefit outweighs the CI complexity here.
Decision 2: FastAPI vs. Django vs. Flask
Choice: FastAPI — already in your stack, but worth justifying.
The Pydantic-based request/response models are the killer feature for this project specifically: they double as your data contracts. When a route returns a PlayerPrediction model, that schema is enforced, auto-documented in OpenAPI, and trivially type-checkable in tests. Django would be over-engineered (we're not building admin/auth-heavy CRUD), and Flask would force you to assemble Pydantic + validation + OpenAPI manually.
Decision 3: XGBoost vs. LightGBM vs. Neural Nets
Choice: Both XGBoost and LightGBM, with a clean abstraction. Train both, ensemble them, present comparative metrics.
Why not deep learning? Tabular sports data with ~thousands of training examples is the exact regime where GBDTs dominate, and using a neural net here would actually signal you don't know which tool fits the problem. The right ML signal to send is: "I picked the right model family and tuned it well," not "I used the trendiest model."
However — and this is the nuance — keep the model interface abstract enough (BaseModel with fit, predict_proba, feature_importance) that you could add a small neural network later (e.g., for sequence modeling player form over time) without rewriting the training pipeline. Optionality without commitment.
Decision 4: Prediction Targets and Model Structure
This is subtle and important. You have several possible model designs:
Approach	Description	Pros	Cons
A. One model per outcome	Separate models for win, T5, T10, cut	Simple, interpretable	Wastes structure, inconsistent probabilities (win > T5 violations possible)
B. Stroke prediction → simulation	Model predicts a stroke distribution per player per round; outcomes are derived from MC simulation	Internally consistent, single source of truth, naturally produces all outcomes	More complex, harder to calibrate marginals
C. Skill rating → simulation	Model outputs a latent "skill" + variance per player-context; simulation does the rest	Most elegant, most extensible	Most upfront design work
Choice: C, with B as a fallback. Predict a per-player-per-round expected score and a variance (or a full predicted score distribution), then derive all outcome probabilities from simulation. This is also how serious golf models actually work, and it gives the simulation engine real work to do rather than being decorative.
Mention in your README that you considered A and rejected it because it produces incoherent probability sets — that one sentence is worth a lot in an interview.
Decision 5: PostgreSQL Schema Style — Normalized vs. Star Schema
Choice: Normalized OLTP-style core, with materialized views for analytics queries.
The dashboard will run aggregate queries like "show me Scottie Scheffler's SG:APP over his last 20 rounds" — these are slow against a fully normalized schema. Solve it with materialized views refreshed on a schedule, not by denormalizing the source of truth. This is the pattern real analytics platforms use and is a strong signal of database maturity.
Decision 6: Where Does Feature Engineering Live?
Choice: A dedicated features/ module with two execution modes — batch (for training) and online (for inference) — sharing the same code.
The trap here is the classic "training/serving skew" problem: features computed differently in training vs. inference produce silent bugs. The fix is to write every feature as a pure function over a well-typed input, and have both pipelines call the same functions. This is straight out of the Feature Store playbook (Feast, Tecton) without needing the full infrastructure.
Decision 7: Frontend State Management
Choice: TanStack Query (formerly React Query) for server state, Zustand for the small amount of local UI state, no Redux.
Redux is overkill and signals you haven't kept up with the React ecosystem. TanStack Query handles caching, refetching, loading/error states, and stale-while-revalidate semantics for free, which is exactly what a data-heavy dashboard needs. Zustand handles things like "which tournament is selected" or "is the betting panel expanded" in ~10 lines of code.
Decision 8: Charting Library
Choice: Visx or Recharts for standard charts, D3 directly for one or two custom visualizations.
Have at least one bespoke D3 visualization — for example, a strokes-gained "shot trail" or a course-overlay heatmap. Recharts-only screams "template dashboard." One genuinely custom viz signals you can do real frontend work, not just wire up components.
Decision 9: Authentication
Choice: Skip it. Single-user demo, deployed behind basic auth or a simple JWT with a hardcoded demo login.
Don't burn time on Auth0 or full OAuth flows. A hiring manager evaluating an analytics portfolio does not care that you can wire up OAuth — they care about the models and the data engineering. If asked, you say "single-tenant by design; auth would be the first thing added for multi-user."
Decision 10: Containerization Strategy
Choice: docker-compose for local dev with services for api, postgres, redis, frontend, pipeline-worker. Production deploy uses the same images.
Don't introduce Kubernetes for a single-instance deployment — that's another "trendy but wrong tool" trap. If asked "would this scale to multi-region," your answer is "yes, the stateless API is k8s-ready, the database would need read replicas, and the pipeline worker is already queue-driven" — which is the right level of forward-looking without over-engineering the actual build.

4. Phased Build Strategy
The phasing is designed so that every phase ends with a demoable artifact. This matters for portfolio purposes — if you stop after any phase, you still have something to show.
Phase 0 — Foundation (Week 1)
Goal: Skeleton that runs end-to-end with placeholder data.
* Monorepo scaffolded, docker-compose up works
* FastAPI app responds to /healthz
* Postgres reachable, Alembic migrations configured
* React app shells with routing, Tailwind set up, fetches from /healthz
* CI: lint + typecheck + run-on-PR
* README with architecture diagram
Demo: "the whole stack boots." Sounds trivial, but recruiters absolutely notice when a project's docker-compose up actually works on first try.
Phase 1 — Data Layer & Mock Provider (Weeks 2–3)
Goal: Realistic mock data flowing through the schema; the abstraction that DataGolf will later plug into is fully defined.
* DataProvider interface defined (this is the most important deliverable of the phase)
* MockDataProvider generates ~5 years of synthetic but statistically plausible tour data
* Postgres schema designed and migrated
* Ingestion pipeline writes mock data into Postgres
* A few read-only API endpoints: /players, /tournaments, /players/{id}/recent-rounds
The mock data design is critical and I'll detail it in section 9 — it needs to be realistic enough that the models you train on it produce sensible results, otherwise the whole project's outputs look broken.
Demo: "you can browse players and tournaments in the dashboard, backed by a real schema."
Phase 2 — Feature Engineering & First Model (Weeks 4–5)
Goal: One trained model producing real predictions for a tournament.
* Feature engineering module with strokes-gained-style features, recent form, course fit
* Training pipeline using XGBoost
* Model registry (filesystem-based to start, MLflow optional)
* Calibration step (isotonic regression)
* An endpoint /predictions/{tournament_id} that returns model outputs
* A leaderboard view in the frontend
Demo: "the model predicts this week's field — here are the top 10 win probabilities."
Phase 3 — Simulation Engine (Weeks 6–7)
Goal: Monte Carlo engine that converts skill estimates into full probability distributions.
* Simulation engine: configurable iterations (default 10k), full 4-round simulation with cut logic
* Background job system so simulations don't block the API
* Derive win, T5, T10, make-cut probabilities from simulation output
* Frontend cards showing all four outcome probabilities per player
* Simulation diagnostics page (histogram of finishing positions for a chosen player)
Demo: "10,000 simulations of this week's tournament, computed in <30s, with full outcome distributions per player."
Phase 4 — Betting Edge & Analytics Polish (Weeks 8–9)
Goal: The "wow" features that elevate this above a generic ML project.
* Mock sportsbook odds (still no real integration) with realistic vig
* Edge calculation: model probability vs. implied probability
* Expected value + fractional Kelly sizing recommendations
* Reliability diagrams and Brier score reporting in an "ML diagnostics" page
* Custom D3 visualization (shot trail or SG breakdown radar)
* Player trend pages with rolling SG charts
Demo: "here are the +EV bets this week according to the model, with sizing recommendations and calibration evidence."
Phase 5 — Production Polish & DataGolf Integration (Week 10+)
Goal: Ready to show off; ready to swap in real data.
* Deploy (Fly.io or Railway for backend, Vercel for frontend — cheap and impressive enough)
* Logging, metrics, error tracking (Sentry free tier)
* If/when DataGolf access lands: implement DataGolfProvider, swap it in via config, validate against mock data behavior
* Loom video walkthrough for the README (this is a hiring-manager hack — most people skip it, it dramatically increases the chance someone actually engages with your project)

What's Coming Next
Sections 5–12 (database schema, data pipeline, feature engineering, simulation engine, mock data strategy, DataGolf integration layer, deployment, portfolio optimization) are each substantial enough to warrant their own focused treatment. Rather than cramming them in at half-depth here, I'd suggest we tackle them in two or three follow-up passes.
A few quick decisions that would help me sharpen the rest:
* Timeline reality check — is the ~10-week phasing above realistic for you, or are you on a tighter (say, 4-week) or looser timeline? It changes how aggressively I scope the simulation engine and the betting features.
* Mock data ambition — do you want the mock data to be "plausible enough to train on" (faster, fine for demo) or "carefully calibrated to match real PGA Tour distributions" (slower, but the models will behave more realistically when you swap in DataGolf)?
* Deployment ambition — happy with a single Fly.io/Railway deploy, or do you want me to design for something more impressive like multi-service on a small cloud account?
Once you confirm those, I'll do a deep pass on sections 5–9 next (schema, pipelines, features, simulation, mock data — the technical core), then a final pass on 10–12 (integration, deployment, portfolio strategy).
