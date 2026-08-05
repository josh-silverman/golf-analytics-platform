# Analyst scripts

One-off, read-only scripts that pull real Path A output plus DataGolf's raw
predictions and the sportsbook market for a single event, and print an
analyst report to stdout. They're what produced the pre-tournament reports in
[`tournament-analyses/`](../../tournament-analyses/) — not part of the
maintained application surface, not covered by `mypy app`, and not run in CI.

They don't touch the model registry or write to the database; each does at
most one HTTP round trip per DataGolf endpoint it needs and dumps its working
JSON to `scripts/output/` (gitignored, regenerated per run).

Each script hardcodes the tournament id and season it was written for — check
the `EVENT`/`THREE_M`-style constant near the top before rerunning one for a
different week.

| Script | What it does |
|---|---|
| `analyze_3m_open.py` | Full data pull: served board, DataGolf raw predictions, sportsbook consensus, SG skill ratings and course-fit decompositions — dumped to `output/3m_open_analysis.json`. |
| `compute_3m_report.py` | Reads that JSON, merges in a fresh DataGolf pull, de-vigs the market, and prints the analyst report sections (top picks, value/fade lists, SG decomposition). |
| `rocket_classic.py` | Same pull-and-report shape as the two above, self-contained for a single event. |
| `grade_and_next.py` | Grades a completed event's served board and DataGolf's raw archive against the actual results (Brier + skill vs. base rate), scores the previously published picks, and looks up the next event. |

Run any of them the same way as the CLI tools in `app/cli/`, e.g.:

```bash
docker compose exec api uv run python -m scripts.rocket_classic
```
