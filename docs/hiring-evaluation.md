# Hiring Evaluation: PGA Prediction Platform as a Portfolio Centerpiece

*Written from the perspective of a hiring manager / senior technical lead at a professional sports analytics organization (DataGolf, Sportradar, DraftKings, a team's analytics department), evaluating this repository exactly as it would be reviewed during a hiring process. Companion document to [technical-due-diligence.md](technical-due-diligence.md), which contains the code-level findings referenced here.*

*Everything below is based only on what is verifiable in the repository as of 2026-07-08.*

---

## 1. First impression

**The first thing a reviewer sees is the biggest problem with this portfolio piece.**

The README opens with **"Status: Phase 0 — Foundation"** and describes the runtime as "the FastAPI scaffold, the React dashboard skeleton, and a docker-compose dev stack." That is four phases out of date. The repository actually contains a trained, registered, calibrated 18-feature model with a validated backtest harness, a full DataGolf integration, a betting-edge product, and 300+ passing tests. The "Highlights" section is labeled **"planned"** for features that shipped months ago, promises a "skill-and-simulate architecture" that was never built (the shipped model is one-classifier-per-market), and advertises a "head-to-head Brier scores vs. DataGolf" benchmark that does not exist as an accuracy comparison. There are **zero screenshots** in the repo (one logo wordmark), no linked live demo, and the ASCII architecture diagram describes the Phase-0 stack.

A hiring manager gives a portfolio README 60–90 seconds. In those 90 seconds this project presents itself as an unfinished scaffold. Most reviewers would stop there, and the ones who don't would only continue because the commit log (62 disciplined, descriptive commits — `v3_dg_preds: DG pre-tournament archive predictions — make_cut +0.065, top_20 +0.053...`) hints that the README is lying in the wrong direction.

**Would I keep reading?** Yes — but only because commit messages and `docs/project-summary.md` (624 lines of dated experimental record) signal there's a real project underneath. A busier reviewer would not. **Initial impact: poor. Underlying substance: immediately redeemed on inspection.** That gap is the defining fact of this portfolio.

## 2. Technical depth

This is where the project earns an interview.

- **ML sophistication — above the bar.** Per-market GBDT heads with per-market calibration strategy (sigmoid for rare markets, isotonic for dense — with a written justification of *why* isotonic degenerates on rare positives). Time-decayed skill ratings with shrinkage to a deliberately below-average prior (with the phantom-edge failure mode that motivated it documented). NaN-native cold-start routing for external features. Model stacking on a vendor's published predictions, treated correctly as a leakage problem first and a feature second.
- **Statistical rigor — unusually good instincts, incomplete execution.** Event-level block bootstrap (the correct correlated unit — most candidates resample rows and get absurdly tight CIs), walk-forward as-of discipline everywhere, chronological calibration splits, a pre-registered promotion gate with a documented record of *reverting failed experiments* (course fit, weather, field shape, shrinkage, odds-as-feature — all closed with evidence). The gaps: no paired-delta significance tests between model arms, nested "independent" holdouts, a reused test window, and an in-sample "track record" on the product UI (see due-diligence §2). A strong candidate flaw profile: the instincts are senior, the statistical bookkeeping is not yet.
- **Engineering complexity — real.** Two-pass field-relative feature extraction, a content-hashed feature registry with dependency resolution, a deterministic model registry, provider abstraction with contract tests, Redis L1/L2 caching with TTL tiers matched to data immutability.
- **Originality / independent problem solving — the strongest signal in the repo.** The documented arc — "win prediction was broken → diagnosed it as a relative-skill problem → built field-relative features → exhausted internal signal → audited every vendor endpoint → validated archive admissibility → stacked external predictions" — is genuine research iteration, not tutorial-following. Negative results are recorded with the same care as wins. Almost no portfolio project does this.

**Verdict: top-decile technical depth for a portfolio project.** The candidate can clearly do the work of a mid-to-senior ML engineer and reasons about leakage and evaluation better than many working data scientists.

## 3. Engineering & software quality

- **Organization:** clean monorepo (backend / frontend / pipelines / docs / infra), conventional layering (api / services / providers / features / ml / domain). Easy to navigate cold.
- **Code quality:** strict mypy, ruff (lint + format) in CI, frozen deps via `uv.lock`, dataclass-frozen domain models. Docstrings explain *decisions and failure modes*, not just mechanics — rare and valuable. Minor debt: a private-API sklearn import, a silent `features.get(name, 0.0)` vectorizer default, one provider-private-method reach-in.
- **Testing:** 267 backend + 42 frontend tests, contract tests across providers, CI running lint/type/test/build on both stacks with concurrency cancellation. Genuinely professional.
- **Documentation:** 2,800+ lines. The three architecture docs (vision/tradeoffs, technical core, integration/deployment) read like a real design review; `project-summary.md` is a dated lab notebook; there's an actual runbook. **Better documentation than most production teams keep.** The one failure is that the front-door README contradicts all of it.
- **Production readiness:** deploy configs exist (`fly.toml`, `vercel.json`), healthz/readyz, structured logging, Sentry dependency present. Missing: monitoring/drift alerting, data versioning, artifact reproducibility guarantees (pickles, unpinned sklearn floor). Call it "credibly deployable," not "operated."

## 4. Portfolio & resume value

**What it demonstrates, verifiably:** end-to-end ML system ownership; leakage-aware evaluation design; feature engineering with documented iteration; vendor API integration with caching and rate-limit handling; full-stack delivery (typed React frontend with its own test suite); honest product framing (the betting UI explicitly disclaims +EV — a maturity signal a sportsbook employer will notice and like).

**Differentiation:** high. The overwhelming majority of sports-analytics portfolio projects are notebooks: scrape Kaggle data, fit XGBoost, report ROC-AUC on a random split. This is a versioned platform with a walk-forward harness and a written experimental record. In a stack of 50 applicant portfolios, this is top 2–3 on substance.

**Role fit, best to worst:**
1. **ML Engineer (platform/applied)** — near-perfect fit; the parity engineering and registry/backtest infrastructure are exactly the job.
2. **Sports Data Scientist / Quant** — strong fit; the evaluation-culture evidence carries it, with interview probing on the statistical gaps.
3. **Analytics Engineer** — overqualified evidence; pipelines/caching/CI alone would clear the bar.
4. **Deep-ML research roles** — weaker; a GBDT with hand-built features is appropriate engineering, not novel ML.

**Resume impact:** meaningful — *if the numbers are framed honestly.* "Validated make-cut Brier skill +0.25 (block-bootstrap 90% CI) on a walk-forward backtest" is a resume line almost no junior/mid candidate can write truthfully. Overclaiming ("beats sportsbooks", Monte Carlo engines that don't exist) would be caught in any competent interview — the repo itself documents that the model does *not* beat the book.

## 5. Public portfolio readiness

**Not ready today.** The substance is 90% there; the presentation is 30% there.

Missing, in priority order:

1. **README rewrite (blocking).** Current one is stale to the point of being false in both directions — it undersells shipped work and promises unbuilt features. It must lead with what exists: the model, the validated numbers with CIs, the product surfaces, one architecture diagram of the *actual* system, and honest caveats.
2. **Screenshots / GIFs (blocking).** Zero exist. Leaderboard, betting-edge board, player trends — three annotated screenshots minimum. Sports analytics is a visual field; reviewers will not run docker-compose.
3. **Live demo or hosted read-only API.** Deploy configs exist; a live URL (even mock-data mode) converts a 90-second skim into a 5-minute session. If hosting the DataGolf-backed version, respect vendor ToS — mock mode is the safe public default.
4. **Results visualization.** The single most persuasive artifact this repo could produce is one chart: calibration reliability curves + skill scores with CIs per market, walk-forward. The data already exists in the harness; it's presentation-only work.
5. **The DataGolf head-to-head benchmark.** Promised in the README, absent in code, and identified in the due-diligence review as the project's central unanswered question ("does the model add anything over its dominant input?"). For a *hiring* audience this doubles as the best possible demo page. Running it is also a risk: if DG-standalone wins outright, the honest framing becomes "a calibration/presentation layer over DG" — still hireable work, but the story must be told carefully.
6. **Reproducibility path for a stranger.** Mock-mode quickstart works (good), but there's no "reproduce the backtest numbers" command documented, no data snapshot, and no experiment artifacts committed. A skeptical senior reviewer cannot verify any headline number.
7. **Storytelling doc.** The experimental record in `project-summary.md` is the project's best asset and is buried. A short "How this model got 10x more accurate — what worked and what didn't" write-up (or blog post) built from it would outperform everything else here for recruiter reach.
8. **Housekeeping:** in-sample "track record" on the UI must be fixed or clearly labeled before any employer sees it (a sharp reviewer will find it in an hour, and it reads badly); remove or gate the `Coming Soon` routes; add DataGolf attribution/ToS note; consider hiding the resume-contradicting "Monte Carlo" references in older docs or reconciling them.

---

## Executive summary

Underneath a badly stale front door is one of the strongest sports-analytics portfolio projects a hiring manager is likely to see: a genuinely end-to-end, leakage-disciplined, honestly-evaluated prediction platform with a written experimental record, real negative results, 300+ tests, and production-shaped engineering. The failure is entirely presentational: the README describes a Phase-0 scaffold, nothing is visualized, no demo is linked, and the repo's best evidence (the validation harness and lab-notebook docs) is invisible unless a reviewer digs. Substance: top decile. Packaging: bottom quartile. The fix is days of work, not months.

## Would I interview this candidate?

**Yes — on the strength of the code and experimental record, despite the README.** The block-bootstrap-by-event choice, the as-of parity discipline, the documented reversions, and the honest "we don't beat the book" framing are things I cannot teach quickly and rarely see in applicants. I would interview for ML Engineer or Sports Data Scientist, and I would probe exactly where the repo is weak: paired significance testing, the in-sample track record, holdout reuse, and "what does your model add over DataGolf's own predictions?" A candidate who answers those four candidly gets an offer-track loop. *Caveat:* this yes assumes the candidate reached the repo past the résumé screen; in a high-volume pipeline, the current README plus no visuals means many reviewers would never see what I saw.

## Top 5 improvements before making this public

1. Rewrite the README around the shipped system: real status, validated metrics with CIs, honest limitations, actual architecture diagram.
2. Add 3–4 product screenshots and one results chart (reliability curves + per-market skill with CIs).
3. Stand up the live demo (mock-mode default) and link it at the top of the README.
4. Fix or clearly label the in-sample UI "track record"; document a one-command "reproduce the backtest" path.
5. Build the DG-standalone vs. v3 benchmark and publish the result — whichever way it comes out, framed honestly.

## The single biggest change that would increase hiring value

**Rewrite the README to tell the true story, with the numbers and one chart at the top.** Every other improvement compounds from it; today the project's first impression actively negates its strongest evidence. (Close second, for interview depth rather than screen-pass: the DG head-to-head benchmark.)

## Scores (1–10)

| Dimension | Score | Basis |
|---|---|---|
| Portfolio quality (as-is, front to back) | **6** | Elite substance dragged down by stale README, zero visuals, no demo link |
| Technical depth | **8** | Top-decile evaluation discipline and iteration record; loses points on missing paired tests, derivative-model question unanswered |
| Engineering quality | **8** | Strict typing, 300+ tests, CI, contract tests, real docs; minor debt (pickles, private APIs, no data versioning) |
| Professionalism | **7** | Code and docs are professional-grade; stale/false README and in-sample UI stat cost real points |
| Presentation | **3** | No screenshots, no charts, no live link, front door describes the wrong project |
| Resume impact | **7** | Rare, truthful, quantified claims available — if framed to match the repo |
| Hiring value | **7.5** | Interview: yes. Offer-track depends on interview performance where the repo is weakest |

## If this repository appeared on GitHub today, how would it compare to successful sports-analytics / ML applicants' portfolios?

**On substance, it beats the vast majority of them.** The typical successful applicant portfolio at this level is a well-presented notebook: public dataset, XGBoost/logistic baseline, random-split AUC, a Medium post. Perhaps 1 in 20 shows a deployed end-to-end system; perhaps 1 in 50 shows walk-forward evaluation with correctly-blocked uncertainty estimates and a documented record of failed experiments. This repo has all of that.

**On presentation, it loses to most of them.** Successful candidates' projects are almost always *smaller but visible*: screenshots, a hosted demo, a crisp README with a chart, a blog post that recruiters and hiring managers actually read. Hiring funnels filter on visibility first and depth second; this project has the order inverted.

Net: as it stands, this repo would outperform successful candidates' portfolios in the final technical round and underperform them at the résumé/README screen — meaning it would too often never get the chance to show its depth. One focused week of packaging (README, screenshots, demo, one results chart, one write-up) flips it into a genuinely top-1% portfolio piece for ML Engineer and Sports Data Scientist roles.

---

*Evaluated against the repository state as of 2026-07-08 (62 commits, active model `golf_v1 @ 0d2efade42ba`, 18-feature `v3_dg_preds`). Code-level evidence for technical claims is cited in [technical-due-diligence.md](technical-due-diligence.md).*
