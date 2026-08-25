# Screenshot shot list

**Why this exists.** All three images in `docs/img/` were captured
2026-08-05 and are the first thing a reader sees in the README. They predate
the provenance work, so they show a board that states no provenance at all,
alongside a record that has since moved from 9 events to 10 and from 2 captured
to 3. Retaking them needs a browser, so the capture is a person's job; this
file is the specification.

Roadmap position: item 1 in the execution order in
[01-roadmap.md](01-roadmap.md).

---

## Applies to every shot

| Setting | Value | Why |
|---|---|---|
| Viewport | **1440 x 900** | Matches all three existing images exactly, so the README's `width="49%"` side-by-side pair keeps its proportions. |
| Theme | **Dark** | All three existing images are dark; a light-theme replacement would look like a different product. |
| Site | the live Vercel deployment | Not `localhost`. A local dev build can show a different record than production if the API is stale. |
| Warm-up | run `scripts/warm_demo.sh` first | The Render free instance spins down after ~15 min idle and the first request takes ~1 min. Without this you will screenshot a loading state. |
| Browser chrome | none | Existing images are viewport-only, no URL bar, no bookmarks. |

Overwrite the existing filenames. `README.md` references them by path, so new
names would mean editing the README too.

---

## 1. `docs/img/leaderboard.png`

**The point of this shot is the provenance block, which the old one predates.**
That is the single most important thing this project can show a reader: the
record is split by how each number was produced, rather than pooled into one
flattering figure.

Must be visible in frame:

- The **"Forward out-of-sample track record"** line.
- The reference line: *"Every figure below compares the served board against
  one reference: predicting the field average for every player."*
- **Both provenance blocks**, which currently read:
  - `Predicted live · 3 events, 350 players graded:` followed by per-market
    skill figures, then *"Recorded before play began, as the site served them."*
  - `Reconstructed · 7 events, 939 players graded:` followed by its own
    figures and the longer caveat about later code producing them.
- The **regime caveat** line beneath them, currently:
  *"Includes 2 of unrecorded coverage out of 10, so this pools more than one
  serving configuration."*
- Enough of the player table beneath to show it is a real board (roughly the
  top 8 rows, as the current image has).

Any event works, since the track-record widget renders on every leaderboard
page. Prefer an upcoming or in-progress event so the "Pre-event predictions,
not updated during play" line is present, as in the current image.

**If the provenance blocks are not on screen, the shot has failed** even if it
otherwise looks good. That block is the entire reason for retaking it.

## 2. `docs/img/report-card.png`

Pick a **completed** event, so `isCompleted` renders the report card and the
`Finish` column. The current image uses the Genesis Scottish Open; any settled
event is fine, and a more recent one is better since ten are now graded.

Must be visible in frame:

- The **report-card explainer**: *"Report card — the model's pre-event board
  vs. what actually happened. The Finish column shows where each player ended
  up (MC = missed cut)."*
- The **`Finish` column** populated, including at least one `MC` row, since
  that is what shows the make-cut market being graded rather than just the
  finishers.
- The aggregate report-card tiles (winner's predicted rank, top-20 hits,
  make-cut accuracy).

## 3. `docs/img/betting-edge.png`

**Also stale — same 2026-08-05 capture.** Not named in the original request,
but it is the same age as the other two and sits in the README at line 515, so
retake it in the same pass rather than leaving one image visibly older.

Must be visible in frame: the market picker, the minimum-probability filter,
and the edge-distribution chart across the field, matching the current
composition.

---

## On named players in these images

Showing real players with real probabilities is **fine here**, and that is a
deliberate decision rather than an oversight. Ledger [§2.8](../ledger.md) draws
the line at reconstructable datasets: a PNG of eight rows is product
demonstration, where a markdown table of thirty players with a `DG win` column
is redistribution. Do not, however, screenshot a full-field export or the CSV
download, which would cross that line.

## After capturing

1. Confirm each file is 1440x900: `sips -g pixelWidth -g pixelHeight docs/img/*.png`
2. Check the README's `alt` text still describes what the image now shows.
   All three alt strings name specific content (player counts, event names,
   which columns appear) and will need updating if you changed events.
3. The alt text for `leaderboard.png` currently describes the Wyndham
   Championship with 147 players. That will be wrong unless you happen to
   reshoot the same event.
