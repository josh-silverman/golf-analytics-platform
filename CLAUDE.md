# Pinpoint Analytics (golf-analytics-platform)

PGA Tour prediction platform. FastAPI backend, React frontend, Postgres
and Redis, deployed on Render.

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

Boards now record `dg_direct_count` (how many players were actually served
DataGolf-direct), because `model_version_id` is stamped `path_a@<id>` before
any DataGolf call and therefore cannot distinguish a healthy Path A board
from one that cold-started the whole field. `/analytics/track-record/forward`
reports the regime split, and the leaderboard shows a caveat line when the
graded set mixes regimes. Boards captured before this shipped report
`dg_direct_count: null` and are counted as "unknown", not as covered.
