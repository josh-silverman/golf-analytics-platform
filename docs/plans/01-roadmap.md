# Roadmap — ledger, automation, repo structure, agents

Companion to [00-audit.md](00-audit.md). Each unit is sized for a single
session, states its dependency and its verification. The governing
principle, per Josh: **extend the existing board-archive/forward-grader
system; do not build a parallel ledger.**

## Decisions (Josh, 2026-08-20)

1. **Render free Key Value has no persistence at all** — the archive can
   be lost on any restart. Durability (A0, revised below) is the only
   urgent item and the whole of the next session. A1–A5 do not start yet.
2. **DataGolf ToS: personal use only, no redistribution.** No
   DataGolf-derived data may be committed to the public repo. The A0
   export target must be private. (The matchup-capture workflow was
   verified clean: it only POSTs to the API and stores to Redis, no git
   writes. Pre-existing exposure: `tournament-analyses/` and the README
   already publish DataGolf per-player probabilities publicly — flagged
   to Josh, decision pending, out of scope for A0.)
3. **Retrain policy: never mid-week.** Retraining is allowed only between
   Monday settlement and Wednesday capture. The A2 dedup rule stays as a
   safety net (prefer earliest live capture), and all snapshots are kept
   so a per-model-version view remains possible.

Numbering groups map to the four goals:
Phase A = prediction ledger + registry (goal 1), Phase B = automation
(goal 2), Phase C = repo structure for lower-touch sessions (goal 3),
Phase D = narrow agents (goal 4).

---

## Dependency order at a glance

Built ✅ / not started ☐. Updated 2026-08-25.

```
✅ A0 (export/backup) ─────────┐
☐  A1 (git SHA provenance)     ├──> ✅ A3 (settlements) ──┬──> ✅ A4a (pin dg_baseline at capture)
✅ A2 (dedup + source split) ──┘                          └──> ✅ A5 (closing-line capture)
                                                                     │
✅ B1 (scheduled board capture) ─────────────────────────────────────┤
✅ B2 (weekly settle + grade) ───────────────────────────────────────┤
                                                                     v
                                                        ☐ A4b (grade + report the baselines)
                                                                     │
                          ┌──────────────────────────────────────────┤
                          v                                          v
                  ☐ D2 (grading commentary)              ☐ D3 (DataGolf calibration audit)

✅ C1 (ops docs + invariants) ── anytime after A2
☐  C2 (make targets + CI for the ledger surface)
☐  B3 (retrain automation — policy decided, may stay manual)
☐  D1 (integrity checker) ── after A0; not gated on data
```

**A4b is the hinge.** Everything in phase D that reads a named baseline waits
on it, and it waits on captured data rather than on code. See its own section
for what that actually means as of 2026-08-25.

---

## Phase A — make the existing ledger complete and trustworthy

### A0 (revised). Archive durability: export + restore ✅ (built 2026-08-20; nightly `archive-export.yml`, see docs/ledger.md §4.1 and §4.2)
- **What**: Make the archive survive a Redis wipe, keeping Redis as the
  live serving store.
  1. Admin-gated `GET /analytics/archive/export`: every board snapshot +
     matchup snapshot as one JSON document (small: a board is ~150
     players × 5 floats).
  2. Admin-gated `POST /analytics/archive/import`: re-seed the archive
     from an export dump. First-write-wins semantics make restore
     idempotent and safe — an import can never overwrite a live capture.
  3. GitHub Actions job committing the export to a **private** GitHub
     repo (fine-grained PAT as a repo secret; DataGolf ToS forbids a
     public target): nightly cron, plus a chained export step at the end
     of `matchup-capture.yml` (and of B1's capture workflow later) so the
     loss window after a scheduled capture is minutes, not a day.
     Lazily-captured boards remain exposed up to 24h until B1 exists.
- **Why this and not a paid Key Value instance or Postgres**: recorded in
  the session notes of 2026-08-20 — export+restore is free, append-only
  (git history is the tamper witness R5 wants), covers both archives, and
  stays useful as the backup layer even if the primary store later moves.
  A paid instance or a DB is still a single mutable copy and doesn't
  remove the need for this job.
- **Depends on**: nothing.
- **Verify**: unit tests for export/import round-trip against the file
  backend (import onto a non-empty archive changes nothing); dispatch the
  workflow manually and confirm the private-repo dump matches production
  (event count vs. `/analytics/track-record/forward`, timestamp vs.
  `/status.last_board_build_at`); re-run → no-change commit skipped;
  flush a local Redis, import the dump, confirm the forward record grades
  identically.

### A1. Git SHA provenance in registry and snapshots
- **What**: Record the serving/training code revision. Add `git_sha` to
  `ModelVersion` metadata (stamped by `app/cli/train.py`) and to
  `BoardSnapshot` (stamped at capture from an env var baked at deploy
  time, e.g. Render's `RENDER_GIT_COMMIT`, falling back to `None`).
  Old artifacts load with `None` — the existing forward-compatible
  deserialization already handles this.
- **Depends on**: nothing (parallel to A0).
- **Verify**: unit tests (round-trip a snapshot with and without the
  field); retrain locally and inspect `metadata.json`; after next deploy,
  confirm a fresh capture carries the SHA.

### A2. Forward-grader ledger hygiene: dedup + source split ✅ (built 2026-08-19 in `46f4f34`; `/track-record/forward` reports events_captured / events_backfilled)
- **What**: (a) Grade at most one snapshot per tournament — prefer the
  earliest `captured_at` with `source="captured"`, else earliest
  backfill — so retraining mid-week can't double-count an event (R1).
  (b) Read `snap.source` and report captured vs. backfilled event counts
  in `ForwardTrackRecord` and the API payload, alongside the existing
  regime split (R2).
- **Depends on**: nothing; do before B-phase automation makes R1 live.
- **Verify**: unit test — two snapshots, same tournament, different
  model versions → one graded event; captured/backfilled counts surface
  in `/analytics/track-record/forward`.

### A3. Immutable settlement records ✅ (built 2026-08-20; see docs/ledger.md §2.4, incl. the initial-pinning decision)
- **What**: On first grade of a completed event, persist a
  `ResultSnapshot` (per-player final position + entry status, settled_at,
  provider name) into the same archive infrastructure, first-write-wins.
  The forward grader reads results from the ledger and falls back to the
  provider only to *create* a missing settlement. The record becomes
  self-contained: predictions + results + grade all pinned (R3).
- **Depends on**: A2 (touches the same grader); A0 exports it too.
- **Verify**: unit test — grade once, mutate the mock provider's results,
  grade again → identical grades; settlement snapshot refuses overwrite.

### A4 (split). Named baseline columns in the forward record

Split into a capture-time half and a reporting half on 2026-08-21,
because they have completely different deadlines. A4a writes data that
can only ever be written *before* an event; A4b reads it and can be built
at any time afterwards. Bundling them would have made the reporting work
gate the storage work, and every week spent building the reporting half
is a week of events permanently missing the baseline.

### A4a. Store `dg_full` on the board snapshot at capture ✅ (built 2026-08-21)
- **What**: Pin DataGolf's own five-market probabilities for the covered
  players onto the board snapshot at capture time, alongside the board
  itself. Raw DataGolf numbers, before `coherent_outcomes` and
  `normalize_field`, so the stored baseline is what DataGolf published
  rather than what our pipeline made of it. Storage only — nothing reads
  the column yet.
- **Why it cannot wait**: DataGolf's pre-tournament feed is not an
  archive of what it said on Wednesday. It keeps updating, and for a
  completed event it returns numbers informed by the finish. A baseline
  fetched at grading time is not a prediction, so a board captured
  without one can never carry the column. The nine events already in the
  record are permanently without it.
- **Also records why**: `dg_fetch_status` (`ok` / `no_coverage` /
  `fetch_failed` / `not_attempted`) sits alongside the baseline, because a
  coverage count of zero is ambiguous between a legitimate cold-start
  board and one captured while DataGolf's live feed still featured last
  week's event. The Wednesday cron refuses a failed fetch at 21:00 so the
  23:30 retry can still do better, and captures it labelled at 23:30.
  See `docs/ledger.md` §2.12a.
- **Depends on**: nothing (it rides the existing capture path).
- **Verify**: `dg_baseline` count and `dg_fetch_status` appear in
  `archive/inspect` per board; absent (pre-A4a) and empty stay
  distinguishable through storage; a strict run refuses a failed fetch
  and writes nothing.

### A4b. Grade and report the named baselines
- **What**: Grade each event's board alongside named baselines and report
  per-market skill for each: (1) field base rate (exists), (2) DataGolf
  raw pre-event probabilities (from A4a's pinned `dg_baseline`; for the
  in-house model this is only a true head-to-head on cold-start players —
  label it honestly, per R6), (3) market implied probability from A5's
  captured lines. Generalizes what `backend/scripts/grade_and_next.py`
  did by hand for the 3M Open.
- **Depends on**: A2, A3, A4a, A5. Only grades events captured after
  A4a/A5 went live, so it is worth building once several such events
  exist rather than immediately.
- **Data reality, measured 2026-08-25 — read this before scheduling the
  work.** There is currently **nothing to grade**. `dg_baseline` is a
  capture-time-only write, A4a shipped 2026-08-21 (`430ccb0`), and
  production's most recent board build is `2026-08-20T02:25 UTC`, one day
  earlier — so **zero archived boards carry a baseline**, and **zero
  closing-line snapshots exist**. The first paired event is the TOUR
  Championship captured 2026-08-26, and it is a **no-cut event**, which
  `forward_track_record.py` excludes from the make-cut market. A4b's first
  real output is therefore n=1 on four of five markets.

  This does **not** mean defer it. The verify criterion below is fixture
  tests and the code needs no real data, so waiting buys nothing. It means:
  build it when convenient, and do not expect the "beats DataGolf" or
  "beats the closing line" claim to carry weight until several more events
  land. Whether they land weekly depends on the FedExCup Fall series being
  covered, which is checkable after the first Wednesday capture and is not
  assumed here.

  Corollary for sequencing: **D1 and the published-claim staleness auditor
  are not data-gated and pay off immediately**, so they are the better use
  of a session while the baseline column still reads n=1.
- **Required exclusion**: a board whose `dg_fetch_status` is
  `fetch_failed` must be excluded from the DataGolf column, not counted
  as a zero-coverage event — otherwise a stale-feed capture drags the
  DataGolf baseline toward "predicted nothing" for reasons that have
  nothing to do with DataGolf. Use `BoardSnapshot.dg_baseline_is_usable`
  rather than re-deriving the test from `dg_direct_count`. Report the
  excluded count alongside the column so the omission is visible.
- **Verify**: unit tests with fixture boards where the model beats /
  loses to each baseline; endpoint payload shows per-baseline rows; 3M
  Open backfilled event reproduces the README table's direction.

### A5. Closing-line capture job ✅ (built 2026-08-21; moved ahead of A4)
- **What**: Snapshot `betting-tools/outrights` (all five markets, all
  books, de-vigged through `services/betting.py`'s field normalization)
  into an immutable per-event archive — the same shape and immutability
  contract as matchup capture. This is the third named baseline and the
  one a bettor actually has to beat.
- **Why it moved ahead of A4**: both A4a and A5 are capture-time writes
  that cannot be applied retroactively, and the TOUR Championship capture
  window closed Wed 2026-08-26 21:00 UTC. A4b is a reporting change with
  no deadline at all. Ordering by deadline rather than by number was the
  only way both capture-time halves landed before that window.
- **Wednesday, not Thursday morning.** The plan above said "shortly
  before Thursday tee-off". It runs Wednesday instead, because the
  start guard (same one as board capture) treats the whole start date as
  too late: no hour on it is provably pre-tee-off across time zones. So
  what is captured is the last pre-event market price, **not the close in
  the strict CLV sense**, and A4b's reporting must not call it a closing
  line without that qualification. A true close needs tee-time-aware
  gating, deliberately not built.
- **Depends on**: audit question 2 — **resolved 2026-08-21**, the
  subscription covers `betting-tools/outrights` on all five markets.
- **Verify**: dispatch captures the upcoming event; second dispatch is a
  no-op; snapshot appears in `archive/inspect` and in the A0 export; a
  dispatch against a started event is refused and reports unhealthy.

---

## Phase B — automate the weekly cycle

### B1. Scheduled board capture ✅ (built 2026-08-20; capture guard + Wednesday cron, see docs/ledger.md §2.2 and §3.6)
- **What**: A cron (Wed evening + Thu morning retry, mirroring matchup
  capture) that triggers capture for the current event instead of relying
  on organic traffic — either by GETting `/predictions/{current}` or via
  a small admin `POST /analytics/track-record/capture-current`. Fixes the
  lazy-capture gap and pins capture timing (R7).
- **Depends on**: A2 (dedup) so a retrain + capture interplay is safe.
- **Verify**: dispatch on a week with an upcoming event → snapshot exists
  (visible in export / `last_board_build_at`); dispatch again → no-op.

### B2. Scheduled settle + grade ✅ (built 2026-08-20; Monday cron, verifies against the record — see docs/ledger.md §2.4)
- **What**: Monday cron: POST an admin settle endpoint that (a) writes
  settlement records for newly completed events (A3), (b) refreshes the
  cached forward record, (c) fails the workflow loudly on error (GitHub
  emails on workflow failure — the alerting channel for now, R8).
- **Depends on**: A3; A4b makes its output worth reading.
- **Verify**: run against a just-completed event: settlement snapshot
  written, forward record event count increments, re-run is a no-op.

### B3. Retrain automation (policy decided — see Decisions §3)
- **What**: Scheduled retrain confined to the Monday-settlement →
  Wednesday-capture window, with the existing feature-set guard,
  registering without activating unless backtest metrics clear the
  current active model's. May legitimately stay manual — the cold-start
  model changes rarely and Path A serves DataGolf-direct regardless.
- **Depends on**: A1, A2, B1, B2.
- **Verify**: dry-run mode output; a registered-but-inactive version
  appears in the registry with git SHA and does not change serving.

---

## Phase C — repo structure for lower-touch sessions

### C1. Invariants + operations doc, wired into CLAUDE.md ✅ (built 2026-08-19 in `e0e50e5`; created docs/ledger.md)
- **What**: One `docs/ledger.md` stating the contracts an agent must not
  break (first-write-wins; OOS admission rule; never grade without
  settlement; capture before Thursday; sources of truth per environment)
  plus the weekly-cycle runbook section, and a short CLAUDE.md pointer.
  This is what lets future sessions act without re-deriving the system.
- **Depends on**: A-phase landing (document what is true, not planned).
- **Verify**: a fresh Claude session, given only the repo, correctly
  answers: where is the ledger, what may overwrite what, how is a week
  graded. (Cheap to actually test.)

### C2. Make targets + CI for the ledger surface
- **What**: `make grade-week`, `make export-archive` style entry points
  wrapping the admin calls; CI job (or slow-lane schedule) covering the
  archive/grader tests already marked slow.
- **Depends on**: B1/B2 endpoints existing.
- **Verify**: targets run against local stack; CI green.

---

## Phase D — narrow agents (only after grading is automated)

### D1. Data-integrity checker
- **What**: Scheduled read-only job comparing production archive vs.
  latest export (drift = R4/R5 alarm), validating snapshot invariants
  (OOS certifiability, dg_direct_share sanity, settlement present for
  completed events, no duplicate tournaments post-A2), failing loudly.
  Start as a plain script on cron; "agent" only if judgment is needed.
- **Depends on**: A0 (needs the export to diff against), A2, A3.
- **Verify**: seed a corrupted/duplicated snapshot in a test fixture →
  checker flags it; clean production run is green.

### D2. Weekly grading commentary
- **What**: After B2 settles a week, generate a draft
  `tournament-analyses/<date>-<event>-results.md` from the graded data
  (served board vs. baselines, biggest hits/misses), in the established
  format of the existing 3M Open / Rocket Classic reports, PR'd for
  Josh's review rather than committed directly.
- **Depends on**: A4b (baselines are the substance), B2 (trigger).
- **Verify**: run against an already-graded historical event; numbers in
  the draft match the analytics endpoints exactly; Josh judges the prose.

### D3. Calibration audit of DataGolf's published probabilities
- **What**: Grade DataGolf's own pre-event probabilities (A4a's pinned
  `dg_baseline`) against settled outcomes from the archive, and report
  calibration sliced by market, field strength, player tier, and
  favourite vs longshot. The question is narrow and answerable: where, if
  anywhere, is DataGolf systematically mispriced? Path A serves DataGolf
  directly to ~95% of the field, so any answer here is a claim about the
  product's own served numbers, not about someone else's model.
- **Depends on**: A4b, plus a meaningful number of graded events with a
  pinned baseline (the nine events already in the record have none). Sits
  after D2.

**Two requirements are part of the unit, not process to bolt on later.**

1. **Pre-registration.** Every hypothesis gets a design doc, written
   before it touches data, stating the slice, the metric, the direction
   of the predicted effect, and what result would falsify it. A
   hypothesis without a written falsifiable claim is not eligible to be
   tested.
2. **Negative-results log.** Every tested hypothesis is recorded with its
   outcome, whether it passed or failed. The log is append-only and lives
   with the analysis, not in a commit message.

**Why, stated plainly:** an agent iterating over hypotheses against the
backtest harness will eventually find something. Four slice dimensions
crossed with five markets is on the order of a hundred comparisons, and
at p < 0.05 several of them are expected to look significant with no
effect present at all. Without a record of how many were tried, a
surviving result is uninterpretable — there is no way to distinguish a
real edge from the best of a hundred coin flips, and the honest reading
of an unlogged search is that it found nothing. This is the same
discipline the feature-space program already followed by recording the
blow-up-rate, course-fit and wave hypotheses as closed negatives; D3
formalises it because an agent can run the search far faster than a
person can remember what it tried.

- **Verify**: a hypothesis with no pre-registration doc is refused by the
  harness; the negative-results log contains every run, including the
  ones that found nothing; a deliberately null slice (random player
  partition) reports no effect.

---

## What I'd do first and why

**A0 (archive export + backup).** The forward record is the asset every
later phase compounds on, and today it lives in one free-tier Redis
instance with no TTL protection against eviction, no backup, and no
tamper witness. Every other unit can be built later without loss; A0
cannot. It is also the smallest unit that touches the full existing
stack (archive protocol, admin gating, cron pattern), so it doubles as a
low-risk proof that the extension seams are where the audit says they
are. A1 and A2 are independent and small; either fits in the same
session if A0 goes quickly.

---

## Execution order from 2026-08-25

The "what I'd do first" note above is the *original* framing and A0 is long
since built. This is the current queue, in dependency order, with what
actually gates each one. Chores that are not roadmap units are included
because they compete for the same sessions.

**Done.**

- Repo hygiene: triage REMOVE bucket cleared, the two REVIEW items decided
  (`fly.toml` deleted, `warm_demo.sh` kept and registered), and the triage
  tool's own self-referential false positive fixed. 2026-08-25.
- DataGolf redistribution exposure closed and ledger §2.8 promoted from
  `[convention]` to `[enforced]` with a CI guard. 2026-08-25.
- B2's first real run verified: BMW Championship settled 2026-08-24, ten
  graded events, captured block at three.

**Open, in order.**

| Order | Unit | Gated on | Notes |
|---|---|---|---|
| 1 | Retake `docs/img/*.png` | a person with a browser | All three are from 2026-08-05 and predate the provenance copy the leaderboard now renders. Shot list in [03-screenshot-shotlist.md](03-screenshot-shotlist.md). |
| 2 | Observe the 2026-08-26 capture | Wed 21:00 UTC | Passive. Confirms A4a/A5 fire for real for the first time. Nothing to build. |
| 3 | **A4b** | nothing, for the code | Highest value, but see its Data reality note: it reports n=1 until events accumulate. Build it fixture-tested. |
| 4 | **D1** integrity checker | A0 only, which is built | **Not data-gated.** Better use of a session than waiting on A4b's n. Thresholds are now settable from two observed real weeks rather than guessed. |
| 5 | Staleness auditor (candidate 3) | nothing | **Not data-gated**, and already overdue: the README's "9 events: 2 captured live" is contradicted by the live API's 10 events / 3 captured. |
| 6 | **D2** grading commentary | A4b, B2 | First unit that exercises judgement rather than checking invariants. |
| 7 | Market-vs-DataGolf adjudicator (candidate 2) | A4b + several paired captures | The slowest to unblock, because it needs both capture-time archives to accumulate together. |
| 8 | **D3** calibration audit | A4b + meaningful n | Last, and correctly so. Pre-registration and the negative-results log are part of the unit, not process to add afterwards. |

Parked and not forgotten: **A1** (git SHA provenance), **B3** (retrain
automation, may legitimately stay manual), **C2** (make targets + CI for the
ledger surface).

Standing constraint that outranks this order: three archives close every
Wednesday at 21:00 UTC and two of them cannot be backfilled (§3.7). A change
that must be live "before the event" is due Wednesday, not Thursday.
