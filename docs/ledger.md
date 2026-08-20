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
| Export/restore | `services/archive_export.py` | `GET/POST /analytics/archive/export|import`, backed up to the private `pinpoint-ledger` repo |

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

### 2.2 Capture only before the event completes **[enforced]**

`_capture_board` (`api/v1/predictions.py`) refuses to capture when the
tournament is `COMPLETED`, when the model's training cutoff is unknown,
or when the field is empty. Capture is best-effort and never raises:
archival must not break serving.

The completed-event refusal is what stops a "prediction" from being
written after the result is known. Combined with 2.1, the first capture
for an event is necessarily pre-event.

Note the backfill endpoint deliberately *does* build boards for completed
events. That is safe only because of the constraints in 2.4 and the
provenance label in 2.5. Do not relax either one.

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

### 2.4 Never grade an event that has not settled **[enforced, but see the gap]**

Two gates, both required:

- Event level: the grader skips any tournament whose status is not
  `COMPLETED`.
- Player level: `_labels()` returns `None` for any entry that is not
  `MADE_CUT` or `MISSED_CUT`, so withdrawals and still-active players are
  excluded rather than scored as losses.

**The gap:** settlement results are re-read from the live provider on
every request and are never stored. The historical record is therefore
not self-contained — it depends on DataGolf still being reachable, still
subscribed, and still returning the same results it returned last week. A
provider-side data revision would silently change a published historical
number with no diff and no alarm. Durable settlement snapshots are
roadmap item A3 (`docs/plans/01-roadmap.md`), not built. Until then,
treat any single grading run as a measurement, not a record.

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
against the record itself: `/analytics/track-record/forward` for event
counts, `/status` for `last_board_build_at`, or the export dump. This
also means retries are safe by design (first write wins), so a
timeout-then-retry is not a failure.

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

### 3.6 Board serving is cached; capture is not idempotent-by-cache

`/predictions/{id}` caches the assembled board in Redis for 6 hours,
keyed by `(tournament, as_of)`. A cache hit returns before the capture
path runs, so "load the leaderboard" does not reliably produce a capture.
Capture is lazy and traffic-dependent — scheduled capture is roadmap B1,
not built. Do not assume an event was captured just because its board is
viewable.

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

You will not have `ADMIN_API_TOKEN` locally. The established pattern is a
temporary `workflow_dispatch`-only workflow that carries the secret,
dispatched once, then deleted in a follow-up commit — archive writes stay
deliberate, human-triggered acts rather than standing automation that
could overwrite production keys on a schedule. Precedents:
`archive-restore-oneoff.yml`, `archive-import-july-boards.yml`,
`forward-backfill-oneoff.yml`, all created, used, and removed.

---

## 5. What is not built

Do not assume these exist. Roadmap detail in `docs/plans/01-roadmap.md`.

| Item | Status |
|---|---|
| A1 git SHA provenance | Not built. Neither `ModelVersion` nor `BoardSnapshot` records the code revision. |
| A3 durable settlement records | Not built. See 2.4. |
| A4 named baselines | Not built. The only baseline is the field base rate. No DataGolf-raw column, no closing-line column. |
| A5 closing-line capture | Not built. `get_outright_odds` exists on the provider; nothing captures it. |
| B1 scheduled board capture | Not built. Capture is lazy; see 3.6. |
| B2 scheduled settle and grade | Not built. |
| D1 integrity checker | Not built. Nothing currently diffs production against the ledger. |

One more standing caveat: under Path A, roughly 95% of a covered field is
served DataGolf's own probabilities. The forward record therefore
measures *what the platform served*, which is mostly DataGolf, not the
in-house model's independent skill. That is a fair claim to make as long
as it is the claim being made.
