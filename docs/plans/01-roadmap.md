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

```
A0 (export/backup)  ──────────┐
A1 (git SHA provenance)       ├──> A3 (settlement records) ──> A4 (baseline columns) ──> B2 (weekly settle+grade job)
A2 (grader dedup + source split) ┘                             A5 (closing-line capture) ─┘
                                    B1 (scheduled board capture)
C1 (ops docs + invariants) ── anytime after A2
D1 (integrity checker) ── after A0
D2 (grading commentary) ── after A4/B2
```

---

## Phase A — make the existing ledger complete and trustworthy

### A0 (revised). Archive durability: export + restore  ← the next session, in full
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

### A2. Forward-grader ledger hygiene: dedup + source split
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

### A3. Immutable settlement records
- **What**: On first grade of a completed event, persist a
  `ResultSnapshot` (per-player final position + entry status, settled_at,
  provider name) into the same archive infrastructure, first-write-wins.
  The forward grader reads results from the ledger and falls back to the
  provider only to *create* a missing settlement. The record becomes
  self-contained: predictions + results + grade all pinned (R3).
- **Depends on**: A2 (touches the same grader); A0 exports it too.
- **Verify**: unit test — grade once, mutate the mock provider's results,
  grade again → identical grades; settlement snapshot refuses overwrite.

### A4. Named baseline columns in the forward record
- **What**: Grade each event's board alongside named baselines and report
  per-market skill for each: (1) field base rate (exists), (2) DataGolf
  raw pre-event probabilities (store `dg_full` on the snapshot at capture
  so the baseline is as immutable as the board; for the in-house model
  this is only a true head-to-head on cold-start players — label it
  honestly, per R6), (3) closing-market implied probability once A5
  captures it. Generalizes what `backend/scripts/grade_and_next.py` did
  by hand for the 3M Open.
- **Depends on**: A2, A3; A5 for the market column.
- **Verify**: unit tests with fixture boards where the model beats /
  loses to each baseline; endpoint payload shows per-baseline rows; 3M
  Open backfilled event reproduces the README table's direction.

### A5. Closing-line capture job
- **What**: Snapshot `betting-tools/outrights` (all five markets, all
  books, de-vig via the existing `services/betting.py` normalization)
  into an immutable per-event archive, on a cron shortly before Thursday
  tee-off — the same shape as matchup capture. This is the third named
  baseline and the one a bettor actually has to beat.
- **Depends on**: audit question 2 (subscription covers outrights);
  pattern from `matchup-capture.yml`.
- **Verify**: manual dispatch captures this week's event; second dispatch
  is a no-op; snapshot appears in the A0 export.

---

## Phase B — automate the weekly cycle

### B1. Scheduled board capture
- **What**: A cron (Wed evening + Thu morning retry, mirroring matchup
  capture) that triggers capture for the current event instead of relying
  on organic traffic — either by GETting `/predictions/{current}` or via
  a small admin `POST /analytics/track-record/capture-current`. Fixes the
  lazy-capture gap and pins capture timing (R7).
- **Depends on**: A2 (dedup) so a retrain + capture interplay is safe.
- **Verify**: dispatch on a week with an upcoming event → snapshot exists
  (visible in export / `last_board_build_at`); dispatch again → no-op.

### B2. Scheduled settle + grade
- **What**: Monday cron: POST an admin settle endpoint that (a) writes
  settlement records for newly completed events (A3), (b) refreshes the
  cached forward record, (c) fails the workflow loudly on error (GitHub
  emails on workflow failure — the alerting channel for now, R8).
- **Depends on**: A3; A4 makes its output worth reading.
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

### C1. Invariants + operations doc, wired into CLAUDE.md
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
- **Depends on**: A4 (baselines are the substance), B2 (trigger).
- **Verify**: run against an already-graded historical event; numbers in
  the draft match the analytics endpoints exactly; Josh judges the prose.

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
