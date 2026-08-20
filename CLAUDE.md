# Pinpoint Analytics (golf-analytics-platform)

PGA Tour prediction platform. FastAPI backend, React frontend, Redis,
deployed on Render. (`app/db/` and the alembic migration are vestigial and
unused — see [docs/ledger.md](docs/ledger.md) §3.4 before wiring anything
into them.)

## Before touching the prediction ledger

Read [docs/ledger.md](docs/ledger.md). It is the contract list for the
forward record: the immutable board and matchup archives, the grader, and
the export/restore path. Required reading before changing anything under
`app/services/{board_archive,matchup_line_record,forward_track_record,archive_export}.py`,
the capture path in `app/api/v1/predictions.py`, or the admin endpoints in
`app/api/v1/analytics.py`.

The four that bite hardest:

- **First write wins** on every archive persist. Never add an overwrite,
  upsert, or delete path. This is what makes the record falsifiable.
- **One graded snapshot per tournament**, captured beating backfilled
  regardless of timestamp.
- **Captured and backfilled stay distinguishable** in every reported
  number. Never present a pooled figure as a live track record.
- **`/status`'s `model_version_id` is not the version boards carry.**
  Boards are stamped `path_a@<v2 cold-start id>`; `/status` reports the
  registry-active v3 model. Different identifiers, both look
  authoritative.

The doc also covers the traps (a timed-out admin job that actually
succeeded, `path_a@…` not meaning Path A ran, lazy capture), the restore
procedure, and what is deliberately not built yet.

## Before writing audience-facing prose

Read [WRITING-STYLE.md](WRITING-STYLE.md). It is a running record of
Josh's corrections to AI-drafted writing, with before/after examples,
mirrored from the `portfolio` repo.

Read the scope table in that file before applying it. Short version:

- **Full rules** for anything a reader outside the project sees: the root
  README intro, published write-ups, and any text headed for a portfolio
  article.
- **Partial** for `tournament-analyses/`. Those are working notes, so keep
  the precise terminology and traceable numbers. Still no em-dashes and
  no self-congratulation.
- **Not at all** for `docs/`, runbooks, code comments, and commit
  messages. Precise technical vocabulary is correct there. Do not
  simplify "calibration" or "confidence intervals" out of an engineering
  doc.

The most common mistakes, in order: em-dashes, "not X, it's Y"
constructions, metaphors where a literal statement works, sentences that
announce the significance of a point instead of making it, and anything
claiming superiority over other people's work.

When Josh flags a line, fix it, add a dated Log entry to
WRITING-STYLE.md, and mirror the change to the `portfolio` repo.

## Closed issue (kept for context)

`CachingProviderWrapper` used to implement `get_pretournament_preds` but
not `get_pretournament_full_preds`, so Path A serving fell back to the v2
SG-only model for every player and the served win probabilities were
compressed roughly 10x. **Fixed 2026-07-29 in `3dc3ff8`**; a regression
test in `tests/test_caching_provider.py`
(`TestPretournamentPredsPassThrough`) now pins both delegations, since the
failure mode is silent (the base `DataProvider` default returns `{}`
rather than raising). Boards served before that date still carry the bug,
which is what the 3M Open grading measured.

Boards now record `dg_direct_count` so a healthy Path A board can be told
apart from one that cold-started the whole field, since `model_version_id`
cannot express the difference. Details and the resulting regime split in
[docs/ledger.md](docs/ledger.md) §3.2.
