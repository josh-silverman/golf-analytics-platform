# Agent candidates — unscoped

**Status: candidates, not roadmap units. None of these is approved, scoped,
or estimated.** They are written down so the decision to build or drop each
one is deliberate. `01-roadmap.md` holds the units with agreed scope; if one
of these is ever promoted it moves there and is rewritten as a scoped unit.
This file is deliberately not that.

Written 2026-08-24, after A5 and A4a landed.

## The two filters applied to everything here

**1. Model skill is a closed question.** The in-house model could not
consistently beat DataGolf on covered players, which is why Path A serves
DataGolf directly to ~95% of a covered field. The feature-space program was
closed after blow-up rate, course fit, and R1 tee-time wave all returned
negatives. Any agent whose purpose is to find more predictive skill in the
model is attacking a question that has already been answered, at length,
with a documented answer.

**2. The differentiated asset is an evaluation instrument, not a
predictor.** What this project has that almost nobody else has is a growing
immutable archive of DataGolf's pre-event probabilities paired with settled
outcomes — and, from the first Wednesday capture on 2026-08-26, the pre-event
book consensus for the same field. Anyone can query DataGolf's current numbers. Almost nobody has a
tamper-evident record of what DataGolf said *before* events, joined to what
happened. Proposals that use that asset are preferred; proposals that would
work equally well on any analytics repo are suspect.

A third filter emerged while writing this and is applied throughout: **if the
work needs no judgment, it is a test or a script, not an agent.** Two
candidates were cut on exactly that basis and are recorded below with what to
build instead.

---

## 1. Pre-capture readiness check — **closed 2026-08-24**

**Verdict, 2026-08-24: largely redundant, and the surviving gap is not a
pre-flight check.** Re-examined against the `dg_fetch_status` design that
shipped 2026-08-21. Taking the four checks the original proposal listed:

| Original check | Status |
|---|---|
| Has the DataGolf preds feed rolled over to this event? | **Built.** This is exactly `dg_fetch_status` (§2.12a). |
| Is the field published? | **Built.** `CaptureOutcome.NO_FIELD`, and the job fails loudly. |
| Does the feed's event name resolve to a catalog tournament? | **Built.** `EVENT_NOT_IN_CATALOG` refuses and reports unhealthy. |
| Do the five outright markets return the shapes the parser expects? | **Not built, and nothing else covers it.** |

The first three are not merely detected but *acted on*, which is strictly
better than a report: the 21:00 run refuses to pin a degraded board so the
23:30 retry can still do better. Detecting the same condition two hours
earlier buys nothing, because there is no manual remedy — you cannot make
DataGolf roll its feed over or publish a field. **The pre-flight framing was
wrong and is dropped.**

### What survives: the closing-line archive never got the honesty treatment

A4a's boards record *why* they have no DataGolf coverage. A5's market lines
record nothing equivalent, and their degradation is silent and reports
healthy. Two failure modes, both verified against the shipped parser on
2026-08-24:

- **A book switching from American to decimal odds.** `_parse_american("2.50")`
  returns `2`, which is not a valid American price — real ones are never
  between −100 and +100. It is stored as if it were, and
  `american_to_implied_prob(2)` yields **0.98**. Every player in the market
  would be recorded at a 98% implied probability, permanently, with the
  workflow green.
- **DataGolf flattening the nested `datagolf` object to a plain string.** The
  parser reads `dg_baseline=None` for every line and still reports
  `offered: True`. DataGolf's own line vanishes from the archive silently.

Only if *all five* markets fail does capture report `NO_MARKETS` and fail. A
partial shape change captures, reports healthy, and is pinned by
first-write-wins. Both undocumented shapes already found by probing (`odds`
as a message string; `datagolf` as a nested dict) say the feed's shape is not
a stable contract.

**Scoped-down unit, and it is not an agent.** Give `ClosingLineSnapshot` the
same treatment `BoardSnapshot` got: a recorded capture status, plus
value-range validation (an American price outside ±100 is not a price), so a
shape change either refuses at 21:00 or is captured with an honest label at
23:30. Symmetric with §2.12a, small, and it closes the gap where the original
proposal was actually right.

**Built 2026-08-24**, before the archive held anything, as
`LineFeedStatus` + the ±100 range check (ledger §2.11a). Verified against the
live feed by asking DataGolf for `odds_format=decimal`: the strict run now
refuses with 1181 values rejected and writes nothing, the retry captures it
labelled, and the American feed still captures clean with zero rejections.
This candidate is closed.

**How you would know it was producing garbage.** Same shape as
`dg_fetch_status`: seed the parser with a decimal-odds feed and a flattened
`datagolf` object and confirm each is refused or labelled rather than stored
as valid. If it starts refusing captures on weeks the feed was fine, the
range check is too tight — but note that the range check is an arithmetic
fact about American odds, not a heuristic, so it should never fire spuriously.

---

## 2. Market-versus-DataGolf adjudicator

**What it does, and on what trigger.** After settlement, over the paired
archives: where did DataGolf's pre-event probabilities and the pre-event book
consensus disagree, and which of them was closer to what happened? Sliced by
market and by player tier. The question is not "can we bet this." It is
"which of these two priors is better, and where" — which is a question about
the instrument, not about the model.

**Evidence from this repo.** A4a pins DataGolf's raw five-market
probabilities to the board at capture; A5 pins every book's price across five
markets for the same field, the same evening, immutably. Both sides of the
comparison exist together for the first time from the 2026-08-26 capture, and
nothing currently reads them together.

The analysis shape is already proven here. The matchup line record runs
exactly this structure — DataGolf's own line against real book prices, graded
on settled outcomes — and it returned a decision-grade **negative**: 2023-2026
ROI +1.3% with a confidence interval including zero, which killed the
scanner thesis. A method with a track record of producing usable negatives is
the right one to point at a new question.

**What it needs that does not exist.** A4b's market column: the join from
captured closing lines to settlement records is not built. Several weeks of
paired captures, which cannot be hurried. And a resolution of the de-vig
caveat noted in `closing_line_archive`: `devig_field_odds` normalizes a
market to its theoretical field total (one winner, five top-5s), which is
wrong when the books priced only part of the field. D3's pre-registration
and negative-results log should govern this from the first hypothesis, not
be retrofitted.

**How you would know it was producing garbage.**

- Edge concentrated in longshots is almost certainly the de-vig
  normalization artifact rather than signal.
- Edge that exists at "any price" but disappears at "best available price"
  is the line-shopping artifact the matchup work already identified.
- Any result without a pre-registered falsifiable claim is uninterpretable
  by construction, whatever it says.
- Sanity anchor: pointed at the matchup archive, it must reproduce the known
  negative. If it finds an edge there, it is wrong.

**Why this is not D3.** D3 asks whether DataGolf's published probabilities
are calibrated against outcomes. This asks who wins when DataGolf and the
market disagree, which needs both pre-event captures joined to the same
field. It could not have been proposed before this week.

---

## 3. Published-claim staleness auditor

**What it does, and on what trigger.** After each Monday settle, re-read the
audience-facing surfaces that carry frozen numbers — the README record
section, the per-event write-ups in `tournament-analyses/` — and check each
claim against the archive as it now stands. Output is a diff: claims that
have gone stale, claims the record now contradicts, and caveats that are no
longer true. It proposes edits and commits nothing.

**Evidence from this repo.** The README states "As of 2026-08-20 the record
is 9 events: 2 captured live, 7 reconstructed after a storage loss." That
record now grows automatically every week, so the sentence is stale within
days of being written.

More telling, the README already carries hand-written staleness caveats: a
block noting that its Brier/skill/log-loss point estimates were computed
before the normalization fix, and a warning on the make-cut row that the
figure is contaminated by no-cut FedExCup events under a bug since fixed.
That debt is real, it accrues, and it is currently paid by hand.

And the failure has shipped before. The leaderboard presented a
7-of-9-reconstructed record as though it were a live one, with unnamed
baselines, until it was corrected. The live surfaces now compute their claims
from the record — `summarizeTrackRecord` derives its wording from
`events_captured` and `events_backfilled` — so they can no longer drift
numerically. The static published prose is exactly where the remaining
exposure sits.

**What it needs that does not exist.** A mapping from published claim to the
archive query that supports it. Today that connection exists only in the head
of whoever wrote the sentence, which is why the caveats are hand-written.
Read access to the record from a context that can also read the repo.

**How you would know it was producing garbage.** Its output should be
overwhelmingly deletions, caveats, and number updates. An agent generating
new promotional prose has drifted off task and should be stopped. Every flag
must cite both the source line and the archive number that contradicts it; a
flag with only one of those is noise. Seed test: change "9 events" to "40
events" and confirm it catches it. If it starts flagging wording rather than
facts it has wandered into [WRITING-STYLE.md](../../WRITING-STYLE.md)'s job,
which is a different job and a human one.

**Why this is not D2.** D2 drafts new commentary for a newly graded event.
This audits prose already published against a record that has moved
underneath it.

---

## 4. Dead-weight triage report — **built 2026-08-24**

Lives at `backend/app/cli/triage.py` (`python -m app.cli.triage` from
`backend/`), with the keep register at [`docs/keep-register.toml`](../keep-register.toml)
and seed tests in `backend/tests/test_triage.py`. The disqualifying
condition below is enforced by
`test_never_recommends_removing_anything_the_register_protects`, which runs
in CI's fast lane rather than being marked slow — a rule nothing checks is
a rule you find out about after the deletion.

**What it does, and on what trigger.** Not a cron. On demand, and at the
moments debris is actually created: a feature hypothesis closes, a deploy
target is dropped, a roadmap unit ships. It produces a **classified
inventory, never a deletion**. Every candidate lands in one of three buckets,
each with the citation that justifies it:

| Bucket | Meaning |
|---|---|
| `remove` | Nothing references it and no documented reason to keep it. |
| `keep — documented reason` | Dead by every static measure, deliberately retained. The reason is cited. |
| `keep — reader pending` | Written but not yet read, because the reader is a roadmap unit that is not built. |

The detection half is mechanical: unreferenced-symbol analysis, import-graph
reachability, `git log` recency, tracked-versus-ignored status. **The
classification half is the entire value**, because in this repo the
mechanical answer is confidently wrong about the cases that matter most.

**Evidence — the removable side is real, and it accumulates.**

- `backend/scripts/` is tracked and holds per-event one-offs:
  `analyze_3m_open.py`, `compute_3m_report.py`, `rocket_classic.py`. One
  arrives per tournament, so this grows for as long as the project runs.
  `grade_and_next.py` sits beside them and is cited by roadmap A4b as the
  thing to generalize, so it belongs in `keep — reader pending`. Telling
  those two groups apart is judgment, not `git log`.
- `backend/fly.toml` is a dead deploy target — the Fly trial ended and Render
  is live — and it is still referenced from `README.md`, `docs/runbook.md`,
  and `docs/project-summary.md`. Removing the file means fixing three
  documents, which is the part no linter will tell you.
- Several `docs/` files date to 2026-07-09 and predate Path A, the ledger,
  and the current deployment (`rank-native-model-design.md`,
  `technical-due-diligence.md`, `project-brief.md`). Whether they are
  superseded or are deliberately-frozen historical records is a judgment
  call, and it is the one worth making explicitly rather than by neglect.

**Evidence — three things that look exactly like fat and are load-bearing.**
Each is a concrete seed test, and together they are why this must not delete.

- **`app/db/` and `alembic/versions/808b57c7b9d5_initial_schema.py`.**
  Confirmed vestigial: nothing outside `app/db/` imports it, and
  `render.yaml` provisions no Postgres. Dead by every static measure, and
  **deliberately kept**. `/readyz` was broken in `f265744` by precisely the
  assumption that it was live, and §3.4 exists so nobody re-derives that the
  hard way. Deleting it deletes the warning, which is the opposite of
  cleanup.
- **`backend/models/golf_v1/`**, 8MB across 23 tracked files. Old model
  versions look like stale artifacts. They are how a board's
  `model_version_id` stays interpretable and how `training_data_through`
  certifies a snapshot as out-of-sample (§2.6). Pruning them silently
  un-grades parts of the archive.
- **`BoardSnapshot.dg_baseline` and `dg_fetch_status`.** Written on every
  capture since 2026-08-21; nothing reads them, because A4b is not built. A
  dead-field detector flags them entirely correctly, and the correct action
  is the opposite of what it implies: these are capture-time writes that
  cannot be backfilled, so removing them destroys data no later work can
  recover. This repo is structurally full of deliberately-unused-yet code,
  because capture always precedes its reader by design.

**A fourth trap, in the other direction.** `backend/diagnostics/` (264K of
sweep logs from the closed feature-space program) and
`docs/walkthrough-notes.md` are both **explicitly gitignored** —
`backend/.gitignore:1` and `.gitignore:48`. They are not repo fat at all;
they are deliberately-local working files. A tool reasoning from `git` cannot
see them, and a tool reasoning from the filesystem would flag them as debris.
Both readings are wrong. The correct bucket is "local scratch, out of scope,"
and knowing that requires reading `.gitignore` as a statement of intent
rather than as a filter.

**What it needs that does not exist.** A machine-readable "keep, and here is
why" register, so the classifier checks against recorded intent instead of
re-deriving it from comments. §3 of the ledger records some of these reasons
in prose; the rest live only in commit messages. Without that register the
tool rediscovers `app/db/` as dead on every single run, which is how a
cleanup tool becomes a thing you stop reading.

**How you would know it was producing garbage.** One disqualifying test: **if
it ever recommends removing `app/db/`, a registered model version, or a
capture-time field without citing why the documented reason no longer
applies, it is unusable** — that is not a tuning problem. Precision over
recall, explicitly: missed debris costs disk space, while a deleted
traceability artifact costs the interpretability of the record. Its output
should also shrink across runs; the same items resurfacing every time with no
decision attached means it is producing a nag rather than a queue. Seed test:
it must classify `app/db/` as `keep — documented reason` and cite §3.4.

**Why report-only.** Same standard used to cut the provider-delegation
auditor below. The detectable part needs no agent, and the part that needs
judgment is exactly the part where being wrong is irreversible. An agent that
opens a pull request full of deletions inverts that risk.

---

## Considered and cut

The cuts carry as much information as the proposals.

**Anything aimed at model skill** — feature search, ensembling,
hyperparameter sweeps. Cut on the project's own finding. Path A exists
because the model could not consistently beat DataGolf on covered players,
and the feature-space program was closed after three separate negatives.
D3's own warning applies with double force here: an agent iterating
hypotheses against the backtest harness will eventually find something.

**Provider-delegation auditor.** The silent-gap bug is real and recurring:
the 2026-07-29 `get_pretournament_full_preds` gap compressed served win
probabilities roughly tenfold and shipped to production, and then
`fetch_live_matchups`, `fetch_live_outrights`, and
`get_pretournament_full_preds_with_status` each needed the same explicit
pass-through. But detecting it needs no judgment at all. **Build it as a
parametrized test**: for every public method on `DataGolfProvider`, assert
that `CachingProviderWrapper` either overrides it or is deliberately
allow-listed, extending
`tests/test_caching_provider.py::TestPretournamentPredsPassThrough`. Worth
building. Not an agent.

**DataGolf ToS / public-exposure guard.** The exposure is real and
unresolved: per-player DataGolf probabilities sit in the public README and in
`tournament-analyses/`, against personal-use-only terms, and §2.8 is marked
`[convention]` with nothing enforcing it. But a path-and-pattern check in CI
covers most of the prevention, and the actual open question — what to do
about material already published — is a decision, not a detection.

**Ambiguity reviewer.** A reviewer asking "does this change introduce a value
whose meaning is ambiguous?", generalizing the traps in §3 and the
`dg_direct_count == 0` ambiguity that A4a's `dg_fetch_status` resolved. Cut:
no clean garbage signal, and it overlaps ordinary code review without a
sharper contract than "be careful."

**Negative-results librarian.** D3 already mandates the log as part of its
own definition. A separate agent maintaining it adds overhead to a discipline
that only works if the analyst owns it.

---

## Promoting one of these

If a candidate is promoted, it gets a scoped unit in `01-roadmap.md` with
dependencies and a verification clause, and this entry is marked as promoted
rather than deleted — the reasoning above is worth keeping even after the
decision is made.

Current state:

- **1** — closed. The redundant three-quarters were already built; the
  surviving quarter shipped 2026-08-24 as ledger §2.11a.
- **2** — blocked on A4b and on accumulating paired captures. Untouched.
  Note that the block is longer than it looked: as of 2026-08-25 *zero*
  paired captures exist, and the first arrives 2026-08-26. See A4b's data
  reality note in [01-roadmap.md](01-roadmap.md).
- **3** — untouched, and its premise is now confirmed rather than
  predicted. The README claimed "9 events: 2 captured live" while the live
  API reported 10 and 3; corrected by hand on 2026-08-25, which is exactly
  the manual work this candidate exists to remove. Second-cheapest unit on
  the board and not data-gated, so it is worth doing before the numbers
  drift again.
- **4** — built 2026-08-24. Report-only, as scoped. Its own report had one
  false positive, fixed 2026-08-25: `_SELF_DESCRIBING` kept the keep
  register out of the reference index, so nothing could be seen referencing
  it and the tool opened by recommending you delete its own config. Now
  excluded from the report as well as the index, and pinned by a test.
