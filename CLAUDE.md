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

## Known open issue

`CachingProviderWrapper` implements `get_pretournament_preds` but not
`get_pretournament_full_preds`, so Path A serving falls back to the v2
SG-only model for every player and the served win probabilities are
compressed roughly 10x. Anything written about the live board's win
market needs a caveat until this is fixed.
