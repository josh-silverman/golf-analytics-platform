# The prediction ledger — invariants and traps

The forward record is the platform's core asset. Models can be retrained
and features rebuilt, but a corrupted or lost prediction ledger cannot be
recreated: it is evidence about what was predicted *before* events whose
outcomes are now known. Everything in this document exists to keep that
evidence trustworthy.

Read this before changing anything under `app/services/board_archive.py`,
`app/services/matchup_line_record.py`,
`app/services/forward_track_record.py`, `app/services/archive_export.py`,
the capture path in `app/api/v1/predictions.py`, or the admin endpoints in
`app/api/v1/analytics.py`.

Each invariant below is tagged with how it is held:

- **[enforced]** — code plus a regression test fails if you break it.
- **[convention]** — nothing stops you; breaking it silently corrupts the
  record. These are the dangerous ones.

---

## 1. What the ledger is

Two immutable archives, one grader, one backup path.

| Piece | Module | Contents |
|---|---|---|
| Board archive | `services/board_archive.py` | One pre-event prediction board per `(tournament_id, model_version_id)` |
| Matchup archive | `services/matchup_line_record.py` | One pre-event matchup board per `(calendar_year, event_slug)` |
| Forward grader | `services/forward_track_record.py` | Grades completed, out-of-sample boards → `GET /analytics/track-record/forward` |
| Settlement archive | `services/settlement_archive.py` | One pinned results record per tournament, written at first grade (§2.4) |
| Export/restore | `services/archive_export.py` | `GET/POST /analytics/archive/export|import`, backed up to the private `pinpoint-ledger` repo |
| Inspector | `api/v1/analytics.py` | `GET /analytics/archive/inspect`, read-only metadata for debugging (§4.4) |

Storage backend is chosen by `board_archive_backend`: `redis` in
production (`render.yaml`), `file` in dev and tests. Both implement the
same protocol and the same immutability guarantee.

---

## 2. Invariants

### 2.1 First write wins on every archive persist **[enforced]**

`persist()` returns `False` and changes nothing when a snapshot already
exists for that key. Redis enforces it with `SET … NX`; the filesystem
backend with an existence check plus a temp-file rename.

This is the single load-bearing property of the whole system. A forward
track record is only meaningful if the prediction provably predates the
outcome. If a later write could replace an earlier snapshot, then every
number the platform publishes becomes unfalsifiable: a board could have
been silently rewritten after the event with hindsight, and nothing in
the data would show it. Immutability is what converts "we say we
predicted this" into "we can show we predicted this".

Consequences to preserve:

- Never add an update, upsert, or overwrite path to either archive.
- Never delete snapshots to "clean up" the archive.
- A restore (`POST /archive/import`) writes through `persist()` for
  exactly this reason: it can only fill gaps, never overwrite a snapshot
  the live store still holds.
- Pinned by `tests/test_board_archive.py`
  (`test_persist_is_immutable_first_capture`, the Redis equivalent) and
  `tests/test_archive_export.py`
  (`test_import_never_overwrites_an_existing_snapshot`).

### 2.2 Capture only before the event starts **[enforced]**

`services/board_capture.py` holds the one capture decision, shared by the
lazy path (`api/v1/predictions.py`) and the scheduled path
(`POST /analytics/track-record/capture-upcoming`). A guard on only one
path is a guard a future caller bypasses, which is why it lives in one
module rather than in each endpoint.

A board may be captured only while the event has **not started**. Both
signals are checked, and either one refuses:

- `status != UPCOMING` — the provider's own judgment, the only signal
  that reacts to an actual tee-off rather than to the calendar.
- `today >= start_date` — a calendar backstop for a provider whose status
  has not flipped yet. Strict, with no same-day exception: tee times span
  time zones (an Open Championship morning wave is under way before 07:00
  UTC), so no hour on the start day is universally pre-event.

This matters because capture is permanent. Under Path A the
DataGolf-direct probabilities are read from the *live* pre-tournament
endpoint for any not-completed event, so a board built after tee-off
carries numbers that reflect play in progress while presenting itself as
a pre-event board, and 2.1 pins it forever. Feature `as_of` is capped to
the eve and stays clean either way; the contamination vector is the
DataGolf read, not the features. The cost of the strictness is that an
event starting the same day the job runs is refused rather than captured:
deliberate, because a missing board is recoverable by backfill and a
contaminated one is not.

The guard lives in the capture policy, **not** in the archive's
`persist`, because the backfill legitimately writes boards for events
that have already finished (as reconstructions, marked
`source="backfilled"`, see 2.5). Storage stays policy-free. Do not move
the guard down into the archive, and do not relax the backfill's
constraints in 2.4/2.5 to compensate.

Pinned by `tests/test_board_capture.py`, which exercises each signal on a
day the other would allow.

### 2.3 Grade one snapshot per tournament; captured beats backfilled **[enforced]**

The archive legitimately holds several snapshots of one event, because
the key includes `model_version_id` and retraining changes it. Grading
them all would count the tournament twice, including as two blocks in the
event-level bootstrap, which quietly narrows the confidence interval on a
record that has not actually seen more events.

The grader picks one canonical snapshot per `tournament_id`:

1. `source == "captured"` beats `source == "backfilled"`, **regardless of
   timestamp**. Primary evidence outranks reconstruction even when the
   reconstruction was written first.
2. Within the same source, earliest `captured_at` wins.

All snapshots stay in the archive. Deduplication happens at grading time
only, so a per-model-version view remains possible later.

Pinned by four tests in `tests/test_board_archive.py`
(`test_forward_grader_counts_a_tournament_once_across_model_versions`,
`test_live_capture_beats_an_earlier_backfill`,
`test_earliest_live_capture_wins_within_a_source`,
`test_backfill_stands_in_when_no_live_capture_exists`).

### 2.4 Never grade an event that has not settled **[enforced]**

Two gates, both required:

- Event level: the grader skips any tournament whose status is not
  `COMPLETED`.
- Player level: `_labels()` returns `None` for any entry that is not
  `MADE_CUT` or `MISSED_CUT`, so withdrawals, disqualifications, and
  still-active players are excluded rather than scored as losses. Their
  statuses are still stored in the settlement record — pinned but
  ungradeable — and a stored status this build does not recognise is
  treated the same way, never guessed at.

**Results are pinned at first grade (A3, built 2026-08-20).** The grader
reads each event's results from its immutable `SettlementRecord`
(per-player final position and status, `settled_at`, provider name); the
provider is consulted only to *create* a missing settlement, never to
re-read one that exists. First write wins, like the boards, so a
provider-side data revision can no longer rewrite an already-graded
event. Settlements travel in the export/import and appear in
`archive-inspect`. Pinned by
`test_first_grade_pins_settlement_and_ignores_provider_mutation` and
`test_settlements_round_trip_and_refuse_overwrite`; semantic equivalence
with the old provider-path grading is pinned by
`test_grading_from_settlement_matches_grading_from_provider`.

**Settling runs on a schedule (B2, built 2026-08-20).**
`.github/workflows/settle-and-grade.yml` runs Monday 12:00 UTC with a
20:00 UTC retry, calling `POST /analytics/track-record/settle`. That
endpoint adds no capability, since any request to `/track-record/forward`
already pins missing settlements; it makes the timing deterministic and
reports which events were newly pinned. Cost is proportional to *newly*
completed events (one provider field read each), because an event that
already has a settlement is graded without touching the provider, and
settlements persist per event inside the grading loop, so a run cut off
by a client timeout leaves durable partial progress for the retry to
finish. The job decides success by reading `archive-inspect` and the
forward record afterwards rather than by trusting the settle response
(§3.3), and fails when the forward record is unavailable or when graded
events outnumber pinned settlements.

**Initial pinning was deliberate, not accidental.** The 9 events graded
before A3 existed had no settlement records, so the first grading run
after the deploy pinned the provider's *current* view as truth for events
that finished weeks earlier. That is the best available evidence
(DataGolf's settled results for completed events are stable in practice),
but those pins are reconstructions of settlement truth, not captures made
at settlement time — `settled_at` on them records when the pin happened,
not when the event settled. Accepted by Josh, 2026-08-20.

### 2.5 Captured and backfilled must stay distinguishable **[convention]**

Every snapshot carries `source`: `"captured"` (recorded live when the
board was served pre-event) or `"backfilled"` (reconstructed after the
fact by whatever code was current when the backfill ran). The grader
reports `events_captured` and `events_backfilled`, which always sum to
`events`.

A backfill is leakage-free — `as_of` is capped to the event's eve, it
reads DataGolf's pre-event archive, and it is admitted only if the model
trained strictly before the event — but it is **not** what production
actually served at the time. It is a reconstruction by later code. The
two are different classes of evidence and must never be presented as one
number.

Rules that follow, none of them enforced by a test:

- Never publish a pooled figure as a "live track record" without the
  split. If a surface has room for only one number, it must be the
  captured-only one, or the text must say the figure includes
  reconstructions.
- Never let a backfill overwrite or displace a live capture. Invariants
  2.1 and 2.3 both protect this; keep them that way.
- When adding a new reported aggregate, carry the split through to it.

As of 2026-08-20 the record is 9 events: 2 captured, 7 backfilled. A
headline number drawn from it is mostly reconstruction, and saying so is
the difference between an honest record and a misleading one.

### 2.6 Out-of-sample admission is strict and uncertifiable means excluded **[enforced]**

`BoardSnapshot.is_out_of_sample(start_date)` requires
`model_trained_through < start_date`, strictly. A snapshot with
`model_trained_through = None` is treated as not certifiable and
excluded, never given the benefit of the doubt.

This is what separates `/track-record/forward` from `/track-record`. The
latter grades the *active* model against events it may have trained on,
so it can be inflated by memorisation. Do not blur the two, and do not
add a "probably out of sample" tier.

### 2.7 Exports must stay deterministic **[enforced]**

`export_archives()` sorts boards by `(tournament_id, model_version_id)`
and matchups by `(year, slug)`, and includes no timestamp. An unchanged
archive therefore produces a byte-identical document, which is what lets
the backup job skip empty commits so the ledger history grows only when
the record does.

Adding a generation timestamp, a random ordering, or an unsorted dict
would produce a commit per run and destroy the signal in that history.
Pinned by `test_export_is_deterministic_regardless_of_write_order`.

### 2.8 DataGolf-derived data never enters the public repo **[convention]**

DataGolf's terms are personal use only, no redistribution. This
repository is public. The export dump goes to the private
`pinpoint-ledger` repo via a write-scoped deploy key
(`LEDGER_DEPLOY_KEY`); the export workflow logs snapshot counts only,
never content, because Actions logs on a public repo are public.

Known pre-existing exposure, unresolved and Josh's call: the README and
`tournament-analyses/` publish DataGolf per-player probabilities and
skill ratings. Do not add more without asking.

### 2.9 Admin endpoints stay admin-gated and 404 when unconfigured **[enforced]**

`/archive/export`, `/archive/import`, `/track-record/forward/backfill`,
and `/matchups/capture` all require `X-Admin-Token` matching
`settings.admin_api_token`, and return 404 (not 401 or 403) when the
secret is unset or wrong, so the endpoints do not advertise their
existence in an unconfigured deployment.

The token lives only as a Render env var and a GitHub Actions secret. A
local session does not have it and cannot call these endpoints directly;
drive them from a workflow instead. See 4.3.

### 2.10 Retraining happens only between Monday settlement and Wednesday capture **[convention]**

Josh's policy, 2026-08-20. A retrain mid-week changes
`model_version_id` between an event's capture and its settlement, which
is the exact condition that produces duplicate snapshots per event. 2.3
makes that survivable at grading time, but the policy is what keeps the
archive clean in the first place.

---

## 3. Traps

Things that look like one thing and are another. Each of these cost real
debugging time.

### 3.1 `/status`'s `model_version_id` is not the version boards carry

`GET /api/v1/status` reports the **registry-active** model
(`0d2efade42ba`, the v3 stacked model). Boards served under Path A are
stamped `path_a@<v2 cold-start version>` (currently
`path_a@d69cf2a7323f`), because `get_prediction_service` selects the
newest model whose feature-set hash matches `v2_field_relative()` and
uses DataGolf directly for covered players.

These are different identifiers that both look authoritative. Reading
`/status` and assuming the archive is keyed by that value will lead you
to the wrong conclusion about whether an event is already captured. To
find the version boards actually carry, read a snapshot, or call
`/predictions/{id}` and read `model_version_id` from the response.

### 3.2 `path_a@…` in the version id does not mean Path A ran

The id is stamped when Path A is *configured*, before any DataGolf call.
A board where DataGolf returned nothing (provider bug, outage, uncovered
event) is stamped identically to a healthy one. `dg_direct_count` on the
snapshot is the only way to tell; the grader splits events into
`events_path_a` / `events_cold_start_only` / `events_regime_unknown`
using it, with a 50% coverage floor. Snapshots written before that field
existed report `null` and count as unknown, never as covered.

### 3.3 A job's self-report can be wrong while the job succeeded

Admin endpoints that rebuild boards can exceed the client's timeout while
the server keeps working and commits its writes. On 2026-08-20 the
recovery backfill's first request timed out client-side, the automatic
retry found every event already captured, and the workflow reported
`{"examined": 9, "captured": 0, "skipped": 9}` — while 7 events had in
fact just been reconstructed.

Never trust a job's own summary as the state of the ledger. Verify
against the record itself: `/analytics/archive/inspect` for what is
actually stored (§4.4), `/analytics/track-record/forward` for graded
event counts, or `/status` for `last_board_build_at`. This also means
retries are safe by design (first write wins), so a timeout-then-retry
is not a failure.

### 3.4 `app/db/` and the alembic migration are vestigial

Nothing outside `app/db/` imports it (verify with
`grep -rl "from app.db" app --include="*.py" | grep -v "^app/db"`, which
returns nothing). `render.yaml` provisions no Postgres. `CatalogService`
reads from the provider directly. The SQLAlchemy models and
`alembic/versions/808b57c7b9d5_initial_schema.py` describe a schema that
was never wired up, and `/readyz` was fixed in `f265744` specifically
because it reported not-ready on a database the service never uses.

Do not wire new work into these. If the ledger ever needs a relational
store, that is a deliberate design decision (roadmap A3 and beyond), not
something to inherit by finding the models already there and assuming
they are live.

### 3.5 The mock provider's "today" is a fixed date

`reference_today()` returns a hardcoded anchor (`2026-06-03`) under the
mock provider and the real UTC date otherwise. Date arithmetic that looks
broken in tests is usually this.

### 3.6 A viewable board does not mean a captured board

`/predictions/{id}` caches the assembled board in Redis for 6 hours,
keyed by `(tournament, as_of)`. A cache hit returns before the capture
path runs, so loading the leaderboard does not reliably produce a
capture, and after the event starts the guard (2.2) refuses regardless.

Scheduled capture (B1, built 2026-08-20) is what makes capture timing
deterministic: `.github/workflows/board-capture.yml` runs Wednesday 21:00
UTC with a 23:30 UTC retry. Both runs are on Wednesday, unlike
`matchup-capture.yml`'s Thursday retry, because the start guard would
refuse a Thursday attempt for a Thursday-start event by design; the
retry's real job is the case where the field was not published yet at
21:00. Events that start on a Wednesday get no scheduled capture, since
21:00 is already same-day for them.

The job exits non-zero when the endpoint reports `healthy: false`, which
means an event in the window did not end up with a board. That is
deliberately loud: a missed pre-event window cannot be recovered by
re-running the job, only reconstructed as a backfill.

To check whether a specific event was captured, read
`archive-inspect` (§4.4) rather than inferring it from the leaderboard.

---

## 4. Procedures

### 4.1 Restore the archives after a wipe

See `docs/runbook.md` §9, "Restore the forward archives after a Key Value
wipe". Clone `pinpoint-ledger`, POST
`golf-analytics/archive-export.json` to `/analytics/archive/import`,
verify counts against `/analytics/track-record/forward`. Verified
end-to-end 2026-08-20.

### 4.2 Back up

`.github/workflows/archive-export.yml` runs nightly at 07:30 UTC, on
manual dispatch, and via `workflow_call` at the end of every scheduled
capture. It commits to `pinpoint-ledger` only when content changed.

### 4.3 Run an admin endpoint

You will not have `ADMIN_API_TOKEN` locally: it exists only as a Render
env var and a GitHub Actions secret. Dispatch
`.github/workflows/admin-trigger.yml` instead
(`gh workflow run admin-trigger.yml -f operation=<op>`), then read the
result with `gh run view <id> --log`.

It is deliberately `workflow_dispatch`-only. Manual dispatch is the
authorization boundary, since only someone with write access to the repo
can trigger it and GitHub records who did. **Do not add `schedule`,
`workflow_call`, or `repository_dispatch` to it.** `workflow_call` is the
dangerous one: it would let any other workflow invoke an archive write as
a job step, which is how `matchup-capture.yml` chains `archive-export.yml`
today, and that would end the "writes are human-triggered" property. A
write that genuinely needs to run on a schedule gets its own
single-purpose workflow with one narrow endpoint.

What it can reach is exactly the `operation` dropdown:
`backfill-dry-run`, `backfill`, `archive-inspect`, `archive-import`,
`matchup-capture`, `capture-upcoming`, `settle`. The endpoint path is never free text, so a typo cannot
send a request somewhere unintended.

What it cannot reach, and the rule for adding to it: `/archive/export` is
excluded because the workflow prints response bodies, Actions logs on this
public repo are public, and the export response contains DataGolf-derived
probabilities that may not be redistributed (§2.8). Export therefore has
its own workflow that streams to the private ledger and logs only counts.
Before adding any operation here, apply the same test: **is this
response safe to print in a public log?**

Every write behind the workflow is first-write-wins, so a mis-dispatched
run cannot destroy anything; the worst case is a no-op.

The older pattern (create a temporary one-off workflow, dispatch it,
delete it in a follow-up commit) is retired. It cost four commits and two
deploys per action. `archive-restore-oneoff.yml`,
`archive-import-july-boards.yml`, and `forward-backfill-oneoff.yml` were
its instances; all are deleted.

### 4.4 Work out why an event is not in the record

Two read-only tools, both admin-gated, both reachable from the trigger
workflow above.

`GET /analytics/archive/inspect` (`operation=archive-inspect`, optional
`tournament_id`) lists what the archives actually hold as metadata, with
no probabilities, so it is safe to read in a log and cheap compared with
a full export. Per snapshot it reports `source`, `model_version_id`,
`model_trained_through`, `captured_at`, the outcome count,
`dg_direct_count`, and the two derived answers that matter:
`out_of_sample` (can this snapshot's model certify the event at all,
§2.6) and `canonical` (is this the snapshot the grader actually scores
for its tournament, §2.3). `canonical` is computed by the same
`canonical_by_tournament` helper the grader uses, so the debugging view
cannot disagree with the grader about which snapshot counts.

Working through the usual causes: no snapshot listed at all means capture
never ran (lazy capture, §3.6); a snapshot with `out_of_sample: false`
means the serving model was trained on or after the event start; a
snapshot with `canonical: false` means another snapshot for the same
tournament outranks it, which is normal after a retrain. Whether the
event has *completed* is the one gate this view cannot answer, because
that comes from the catalog rather than the archive — though a
`settlement_records` entry for the event is proof it completed and was
graded at least once (the pin is written at first grade, §2.4), so a
board with no settlement usually means "not completed yet" or "never
graded since completing".

`POST /analytics/track-record/forward/backfill?dry_run=true`
(`operation=backfill-dry-run`) answers "what would a backfill
reconstruct?" without writing anything or building a board. It returns
every candidate in the lookback window with its start date and an
`already_captured` flag. Use it before any real backfill: the window is
otherwise only derivable by reading `_BACKFILL_LOOKBACK_DAYS` and the
cutoff logic by hand, which is how the pre-flight estimate on 2026-08-20
came out wrong. A dry run runs only the cheap checks, so a real run can
still skip a listed candidate whose board turns out to be empty.

### 4.5 Know when a deploy has landed

Render's `autoDeploy` gives no completion signal, and pushing to `main`
does not mean the new code is serving yet. Polling for a *field or route
that only exists in the new build* is the reliable check, because it
tests the running code rather than a build status:

```bash
# Wait for a new route (A0's export endpoint):
until curl -fsS --max-time 90 \
  https://pga-analytics-api.onrender.com/api/openapi.json \
  | grep -q "archive/inspect"; do sleep 30; done

# Or a new response field (A2's provenance split):
until curl -fsS --max-time 90 \
  https://pga-analytics-api.onrender.com/api/v1/analytics/track-record/forward \
  | grep -q "markets_captured"; do sleep 30; done
```

Typical latency is 1 to 3 minutes on the free tier, longer if the
instance is cold. Pick a marker that is genuinely new in the deploy being
waited on; a field that already existed will match immediately and report
success against the old build. `/api/openapi.json` is the cheapest marker
source for a new route, since it needs no auth and no DataGolf call.

Frontend deploys go to Vercel from the same push on their own schedule,
so a green API poll does not imply the page has updated.

---

## 5. What is not built

Do not assume these exist. Roadmap detail in `docs/plans/01-roadmap.md`.

| Item | Status |
|---|---|
| A1 git SHA provenance | Not built. Neither `ModelVersion` nor `BoardSnapshot` records the code revision. |
| A4 named baselines | Not built. The only baseline is the field base rate. No DataGolf-raw column, no closing-line column. |
| A5 closing-line capture | Not built. `get_outright_odds` exists on the provider; nothing captures it. |
| D1 integrity checker | Not built. Nothing currently diffs production against the ledger. |

One more standing caveat: under Path A, roughly 95% of a covered field is
served DataGolf's own probabilities. The forward record therefore
measures *what the platform served*, which is mostly DataGolf, not the
in-house model's independent skill. That is a fair claim to make as long
as it is the claim being made.
