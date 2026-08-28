import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { PlayerDrawer } from '../components/PlayerDrawer'
import { type ArchivedBoard, useArchivedBoard } from '../lib/api/archivedBoard'
import { type Status, useStatus } from '../lib/api/health'
import { useForwardTrackRecord } from '../lib/api/forwardTrackRecord'
import { usePredictions, type PlayerOutcome } from '../lib/api/predictions'
import { useCurrentTournament, useTournaments } from '../lib/api/tournaments'
import type { Tournament } from '../lib/api/types'
import { orderedSkillMarkets, summarizeTrackRecord } from '../lib/forwardRecord'
import { computeReportCard } from '../lib/reportCard'

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

function formatFinish(o: PlayerOutcome): string {
  if (o.final_position != null) return `${o.final_position}`
  if (o.made_cut === false) return 'MC'
  return '—'
}

// Ceiling for the Sleeper tile: a player must have Win probability below
// this to be eligible, so the tile only ever surfaces someone the board
// doesn't expect to win outright. (A gap-based rule — largest Top 20 minus
// Win — was tried first and rejected: that's maximized by near-locks, since
// nothing beats a small Win probability subtracted from a huge Top 20 one,
// so it surfaced the field's strongest player instead of a sleeper.)
const SLEEPER_MAX_WIN = 0.05

// The highest Top 20 probability among players below SLEEPER_MAX_WIN Win —
// someone the board thinks will contend but isn't a realistic winner.
// Returns null when nobody clears the ceiling (every player has some real
// win equity) rather than surfacing a longshot. Ties go to whoever comes
// first in the board's own order (strict `>`), the same tie-break
// `fieldSummary` has always used for its other picks.
function sleeperPick(outcomes: PlayerOutcome[]): PlayerOutcome | null {
  let best: PlayerOutcome | null = null
  for (const o of outcomes) {
    if (o.win_prob >= SLEEPER_MAX_WIN) continue
    if (best == null || o.top_20_prob > best.top_20_prob) {
      best = o
    }
  }
  return best
}

type SortKey = 'win_prob' | 'top_5_prob' | 'top_10_prob' | 'top_20_prob' | 'make_cut_prob'

// Per-column config. ``cellClass`` carries the per-column emphasis (Win is
// de-emphasised — the model does not sharply separate a single winner; Top 20 is
// highlighted as the most reliable market).
const COLUMNS: { key: SortKey; label: string; cellClass: string; barClass: string }[] = [
  { key: 'win_prob', label: 'Win', cellClass: 'text-fg-tertiary', barClass: 'bg-fg-tertiary/20' },
  { key: 'top_5_prob', label: 'Top 5', cellClass: 'text-fg', barClass: 'bg-fg-secondary/20' },
  { key: 'top_10_prob', label: 'Top 10', cellClass: 'text-fg', barClass: 'bg-fg-secondary/25' },
  { key: 'top_20_prob', label: 'Top 20', cellClass: 'text-accent font-semibold', barClass: 'bg-accent/25' },
  { key: 'make_cut_prob', label: 'Make Cut', cellClass: 'text-fg-secondary', barClass: 'bg-fg-secondary/20' },
]

const STATUS_BADGE: Record<string, string> = {
  upcoming: 'bg-warning/15 text-warning',
  in_progress: 'bg-positive/15 text-positive',
  completed: 'bg-fg-tertiary/15 text-fg-tertiary',
}

const STATUS_LABEL: Record<string, string> = {
  upcoming: 'Upcoming',
  in_progress: 'In Progress',
  completed: 'Completed',
}

// Dropdown ordering: live first, then soonest upcoming, then most-recent done.
const _STATUS_ORDER: Record<string, number> = { in_progress: 0, upcoming: 1, completed: 2 }

// Cap on how many completed events the dropdown offers, most-recent first, so
// it doesn't grow unbounded as the schedule accumulates.
const MAX_COMPLETED_EVENTS = 25

function eventLabel(t: Tournament): string {
  const d = new Date(t.start_date).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
  return `${t.name} · ${STATUS_LABEL[t.status] ?? t.status} · ${d}`
}

const SORT_KEYS: SortKey[] = COLUMNS.map((c) => c.key)

function csvEscape(s: string): string {
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

// Export the current (sorted + filtered) board as CSV for offline analysis.
function downloadBoardCsv(filename: string, rows: PlayerOutcome[]): void {
  const header = ['Rank', 'Player', 'Win', 'Top 5', 'Top 10', 'Top 20', 'Make Cut']
  const body = rows.map((o, i) =>
    [
      i + 1,
      csvEscape(o.player_name),
      o.win_prob.toFixed(4),
      o.top_5_prob.toFixed(4),
      o.top_10_prob.toFixed(4),
      o.top_20_prob.toFixed(4),
      o.make_cut_prob.toFixed(4),
    ].join(','),
  )
  const csv = [header.join(','), ...body].join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// Which board the report card scored, in the same vocabulary the forward-record
// widget uses above it: "Predicted live" for a board pinned before play,
// "Reconstructed" for one the backfill rebuilt afterwards. The distinction is
// the difference between a forward record and a re-run, and it has to reach the
// reader on the card itself rather than only in the aggregate widget.
// Exported for reuse by the Track Record page, which shows the same
// captured-vs-reconstructed + out-of-sample caveat for one standalone week.
export function ProvenanceNote({ board, n }: { board: ArchivedBoard; n: number }) {
  const captured = board.source === 'captured'
  const when = board.captured_at ? new Date(board.captured_at).toLocaleDateString() : null
  return (
    <div className="space-y-1 text-xs text-fg-tertiary">
      <p>
        <span className="font-medium text-fg-secondary">
          {captured ? 'Predicted live' : 'Reconstructed'} · {n} players on the board
          {when ? ` · pinned ${when}` : ''}:
        </span>{' '}
        {captured
          ? 'scored against the board recorded before play began, exactly as the site served it.'
          : 'this board was rebuilt after the event from the data available beforehand. No result information goes in, but later code produced it, so it is not a record of what the site showed that week.'}
      </p>
      {!board.out_of_sample && (
        <p className="italic">
          The model that produced this board was not trained strictly before the event, so these
          figures are not an out-of-sample result and the forward record excludes them.
        </p>
      )}
      <p>The Finish column shows where each player ended up (MC = missed cut).</p>
    </div>
  )
}

// Plain-language coverage tile content for the board on screen (H6).
// `model_version_id` reads "path_a@<id>" as soon as Path A is CONFIGURED,
// before any DataGolf call happens — so a board that cold-started the entire
// field is stamped identically to a healthy one. `dg_direct_count` is what
// actually tells them apart. Returns null when there's nothing to show
// (status unreachable), so the tile is omitted rather than guessed at.
function coverageTile(
  status: Status | undefined,
  dgDirectCount: number | null,
  dgFetchStatus: string | null,
  fieldSize: number,
): { value: string; title: string } | null {
  if (!status) return null

  const isPathA = status.serving_strategy === 'path_a'

  if (!isPathA) {
    return {
      value: 'In-house model, all players',
      title: `Serving strategy is "${status.serving_strategy}", not Path A: every player on this board is scored by the in-house model, so DataGolf direct-coverage does not apply.`,
    }
  }
  if (dgDirectCount == null) {
    return {
      value: 'Coverage not recorded',
      title: 'Path A is configured, but this board does not report how many players were priced by DataGolf directly — a fully cold-started board would look identical to a healthy one here.',
    }
  }
  if (dgDirectCount === 0) {
    // NO_COVERAGE means the fetch worked and DataGolf genuinely had nothing —
    // a real cold start. Anything else (FETCH_FAILED, an unexpected OK paired
    // with a zero count, or a null/NOT_ATTEMPTED status) is a broken or
    // unusual fetch producing the same zero, which needs the opposite reaction.
    const legitimateColdStart = dgFetchStatus === 'no_coverage'
    return {
      value: legitimateColdStart
        ? 'No DataGolf prices, in-house model only'
        : 'DataGolf prices unavailable, in-house model only',
      title: legitimateColdStart
        ? 'DataGolf answered but had nothing for this field, so the in-house model cold-started every player. A legitimate result, not a fetch failure.'
        : `DataGolf's fetch did not produce usable data for this event (status: ${dgFetchStatus ?? 'unknown'}), so this board cold-started every player — a degraded result, not a clean cold start.`,
    }
  }
  return {
    value: `${dgDirectCount} of ${fieldSize} priced by DataGolf`,
    title: `${dgDirectCount} of ${fieldSize} players on this board were priced directly by DataGolf; the remaining ${fieldSize - dgDirectCount} cold-started the in-house model.`,
  }
}

// Combined label + value in a single text node on purpose, so the player name
// never appears as its own element (keeps it out of exact-text test queries).
// Exported for reuse by the Track Record page's report-card tiles. `title`
// is an optional tooltip on the value, used by the Leaderboard's Coverage
// tile to keep its longer explanation out of the headline text.
export function SummaryTile({
  label,
  value,
  title,
}: {
  label: string
  value: string
  title?: string
}) {
  return (
    <div className="rounded-lg border bg-surface px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-fg-tertiary">{label}</p>
      <p className="mt-0.5 truncate text-sm text-fg" title={title}>
        {value}
      </p>
    </div>
  )
}

export function Leaderboard() {
  const { data: currentTournament, isLoading: currentLoading } = useCurrentTournament()
  const { data: tournamentsEnv } = useTournaments()
  const { data: trackRecord } = useForwardTrackRecord()
  // Best-effort: the provenance strip degrades to nothing, never to an error,
  // if the registry snapshot is unreachable.
  const { data: status } = useStatus()
  const [searchParams, setSearchParams] = useSearchParams()

  // Selected event: an explicit pick overrides; otherwise follow the current
  // event. Seeded from the URL so a board is shareable/bookmarkable.
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const e = searchParams.get('event')
    return e ? Number(e) : null
  })
  const effectiveId = selectedId ?? currentTournament?.id ?? null

  // Event options for the switcher; falls back to just the current event when
  // the full list isn't available. DataGolf only carries the current week's
  // field, so an upcoming event that isn't "current" has no field to predict
  // yet — offering it leads to either an empty board or a very slow first
  // build. Filtered to in-progress/completed events plus whichever one is
  // current; completed events are further capped to the most recent
  // MAX_COMPLETED_EVENTS so the dropdown (and its slow-cold-load surface)
  // stays bounded.
  const eventOptions = useMemo(() => {
    const list = Array.isArray(tournamentsEnv?.data)
      ? tournamentsEnv.data
      : currentTournament
        ? [currentTournament]
        : []
    const selectable = list.filter(
      (t) => t.status !== 'upcoming' || t.id === currentTournament?.id,
    )
    const sorted = [...selectable].sort((a, b) => {
      const sa = _STATUS_ORDER[a.status] ?? 9
      const sb = _STATUS_ORDER[b.status] ?? 9
      if (sa !== sb) return sa - sb
      const ta = +new Date(a.start_date)
      const tb = +new Date(b.start_date)
      return a.status === 'upcoming' ? ta - tb : tb - ta
    })
    const live = sorted.filter((t) => t.status !== 'completed')
    const completed = sorted.filter((t) => t.status === 'completed').slice(0, MAX_COMPLETED_EVENTS)
    return [...live, ...completed]
  }, [tournamentsEnv, currentTournament])

  // The trimmed eventOptions may not include the selected event (e.g. a
  // bookmarked link to an older completed event beyond the dropdown's cap),
  // so fall back to the full fetched list before falling back to
  // currentTournament — showing the wrong event's name/status badge would be
  // worse than a slightly bigger lookup.
  const selectedTournament =
    eventOptions.find((t) => t.id === effectiveId) ??
    (Array.isArray(tournamentsEnv?.data) ? tournamentsEnv.data : []).find(
      (t) => t.id === effectiveId,
    ) ??
    currentTournament ??
    null

  const isCompleted = selectedTournament?.status === 'completed'

  // Which board this page shows, and where it comes from.
  //
  // A completed event is served from the ledger: the snapshot pinned before
  // play, the same one the report card scores. Anything else is served live.
  // The two are never mixed, so the table and the card above it cannot show
  // different numbers for the same event.
  //
  // The live board is switched off entirely for a completed event. Asking for
  // it would recompute an expensive board with today's model — numbers that
  // are not what was predicted beforehand and that nothing on the page renders.
  const {
    data: predictions,
    isLoading: predictionsLoading,
    isError,
    error,
  } = usePredictions(effectiveId, !isCompleted)

  const {
    data: archived,
    isLoading: archivedLoading,
    isError: archivedError,
    error: archivedErr,
  } = useArchivedBoard(effectiveId, isCompleted)

  // The pinned board for a completed event, the live board otherwise. Null
  // means there is nothing to render — for a completed event that is the
  // honest answer when no snapshot exists, never a fallback recomputation.
  const boardOutcomes: PlayerOutcome[] | null = isCompleted
    ? archived?.available
      ? archived.outcomes
      : null
    : (predictions?.outcomes ?? null)

  const boardLoading = isCompleted ? archivedLoading : predictionsLoading

  // DataGolf coverage for whichever board is on screen: the pinned board's
  // own fields for a completed event, the live board's for anything else.
  const dgDirectCount = isCompleted
    ? (archived?.dg_direct_count ?? null)
    : (predictions?.dg_direct_count ?? null)
  const dgFetchStatus = isCompleted
    ? (archived?.dg_fetch_status ?? null)
    : (predictions?.dg_fetch_status ?? null)

  const [sortKey, setSortKey] = useState<SortKey>(() => {
    const s = searchParams.get('sort') as SortKey | null
    return s && SORT_KEYS.includes(s) ? s : 'top_20_prob'
  })
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(() =>
    searchParams.get('dir') === 'asc' ? 'asc' : 'desc',
  )
  const [query, setQuery] = useState('')
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(() => {
    const p = searchParams.get('player')
    return p ? Number(p) : null
  })

  // Mirror the current view into the URL (replace, so it doesn't spam history).
  useEffect(() => {
    const next = new URLSearchParams()
    if (effectiveId != null) next.set('event', String(effectiveId))
    next.set('sort', sortKey)
    next.set('dir', sortDir)
    if (selectedPlayerId != null) next.set('player', String(selectedPlayerId))
    setSearchParams(next, { replace: true })
  }, [effectiveId, sortKey, sortDir, selectedPlayerId, setSearchParams])

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  // Per-market maxima over the whole field, so each bar scales to the event's
  // leader in that market (filtering doesn't rescale the bars).
  const colMax = useMemo(() => {
    const m: Record<SortKey, number> = {
      win_prob: 0,
      top_5_prob: 0,
      top_10_prob: 0,
      top_20_prob: 0,
      make_cut_prob: 0,
    }
    for (const o of boardOutcomes ?? []) {
      for (const c of COLUMNS) m[c.key] = Math.max(m[c.key], o[c.key])
    }
    return m
  }, [boardOutcomes])

  const rows = useMemo(() => {
    if (!boardOutcomes) return []
    const q = query.trim().toLowerCase()
    const filtered = q
      ? boardOutcomes.filter((o) => o.player_name.toLowerCase().includes(q))
      : boardOutcomes
    return [...filtered].sort((a, b) => {
      const diff = a[sortKey] - b[sortKey]
      return sortDir === 'desc' ? -diff : diff
    })
  }, [boardOutcomes, sortKey, sortDir, query])

  const drawerOutcome = boardOutcomes?.find((o) => o.player_id === selectedPlayerId) ?? null

  // At-a-glance field summary for a live event. Completed events show the
  // report card in this slot instead, so this deliberately reads the live
  // board only.
  const fieldSummary = useMemo(() => {
    const o = predictions?.outcomes ?? []
    if (o.length === 0) return null
    return { sleeper: sleeperPick(o), size: o.length }
  }, [predictions])

  // Report card: how the PINNED pre-event board compared to the result.
  // Shared with the Track Record page — see `lib/reportCard.ts`.
  const reportCard = useMemo(() => computeReportCard(archived), [archived])

  // Coverage tile content for whichever board is on screen.
  const coverage = useMemo(
    () =>
      boardOutcomes
        ? coverageTile(status, dgDirectCount, dgFetchStatus, boardOutcomes.length)
        : null,
    [status, dgDirectCount, dgFetchStatus, boardOutcomes],
  )

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">Leaderboard</h1>
          {selectedTournament && (
            <span
              className={`rounded-full px-2 py-0.5 text-[0.65rem] font-medium uppercase tracking-wider ${
                STATUS_BADGE[selectedTournament.status] ?? 'bg-fg-tertiary/15 text-fg-tertiary'
              }`}
            >
              {selectedTournament.status.replace('_', ' ')}
            </span>
          )}
        </div>

        {/* Event switcher — pick any tournament's board */}
        {eventOptions.length > 0 && (
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs uppercase tracking-wider text-fg-tertiary" htmlFor="event-select">
              Event
            </label>
            <select
              id="event-select"
              value={effectiveId ?? ''}
              onChange={(e) => setSelectedId(Number(e.target.value))}
              className="max-w-full rounded-md border bg-surface px-3 py-2 text-sm text-fg focus:border-accent focus:outline-none"
            >
              {eventOptions.map((t) => (
                <option key={t.id} value={t.id}>
                  {eventLabel(t)}
                </option>
              ))}
            </select>
            {selectedTournament?.purse != null && (
              <span className="text-xs text-fg-tertiary">
                Purse ${(selectedTournament.purse / 1_000_000).toFixed(1)}M
              </span>
            )}
          </div>
        )}

        {boardOutcomes && (
          <p className="text-xs italic text-fg-tertiary">
            {isCompleted
              ? 'The board as it was pinned before play, read from the prediction ledger. Not recomputed.'
              : 'Pre-event predictions, not updated during play.'}
          </p>
        )}

        {trackRecord?.available && trackRecord.markets.length > 0 && (
          <p className="text-xs text-fg-secondary">
            {summarizeTrackRecord(trackRecord, orderedSkillMarkets(trackRecord.markets))}{' '}
            <Link to="/track-record" className="font-medium text-accent hover:underline">
              See the full record →
            </Link>
          </p>
        )}
      </header>

      {(currentLoading || boardLoading) && (
        <div className="space-y-1">
          <p className="text-fg-secondary">
            {isCompleted ? 'Loading the pinned board…' : 'Loading predictions…'}
          </p>
          {!isCompleted && (
            <p className="text-xs text-fg-tertiary">
              The first load after a while warms live tour data from DataGolf and can take a
              minute. It&rsquo;s fast afterwards.
            </p>
          )}
        </div>
      )}

      {!currentLoading && effectiveId == null && (
        <p className="text-fg-secondary">No active tournament to predict.</p>
      )}

      {(isCompleted ? archivedError : isError) && (
        <p className="text-negative">
          Error:{' '}
          {(() => {
            const e = isCompleted ? archivedErr : error
            return e instanceof Error ? e.message : 'Unknown failure'
          })()}
        </p>
      )}

      {!isCompleted && predictions && predictions.outcomes.length === 0 && (
        <p className="text-fg-secondary">
          No field published for this event yet. DataGolf only carries the current
          week&rsquo;s field, so this board is empty until the event is closer.
        </p>
      )}

      {/* Completed event with nothing in the ledger. The board is withheld
          entirely rather than replaced by a recomputation: a board built today
          is not what was predicted before this event, and showing one under an
          event that has already finished invites exactly that reading. */}
      {isCompleted && !archivedLoading && archived && !archived.available && (
        <div className="rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm leading-relaxed text-fg-secondary">
          <p className="font-medium text-fg">No pre-event board was pinned for this event.</p>
          <p className="mt-1">
            The ledger holds no snapshot for {selectedTournament?.name ?? 'this event'}, so there
            is neither a board to show nor anything to score against the result. Nothing is
            displayed in its place: the current model can still produce a board for this field,
            but that is not what was predicted beforehand and it is not a record of anything.
          </p>
          <p className="mt-1 text-xs text-fg-tertiary">
            Boards are pinned by the scheduled Wednesday capture. An event that finished before
            that job existed, or whose capture window was missed, has no snapshot and cannot be
            given one after the fact.
          </p>
        </div>
      )}

      {boardOutcomes && boardOutcomes.length > 0 && (
        <>
          {/* Completed event → report card from the same pinned board the table
              below renders; otherwise field at-a-glance. */}
          {isCompleted && reportCard && archived ? (
            <div className="space-y-2">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <SummaryTile
                  label="Winner"
                  value={
                    reportCard.winner
                      ? `${reportCard.winner.player_name} · board #${reportCard.winnerRank} by win%`
                      : '—'
                  }
                />
                <SummaryTile
                  label="Top-20 hits"
                  value={
                    reportCard.top20ByChance != null
                      ? `${reportCard.top20Hits} / ${reportCard.top20Picks} · ${reportCard.top20ByChance.toFixed(1)} by chance`
                      : `${reportCard.top20Hits} / ${reportCard.top20Picks}`
                  }
                />
                <SummaryTile
                  label="Make-cut accuracy"
                  value={
                    reportCard.cutAcc != null
                      ? `${formatPct(reportCard.cutAcc)} · ${
                          reportCard.cutBaseRate != null ? formatPct(reportCard.cutBaseRate) : '—'
                        } always-guess`
                      : 'no cut at this event'
                  }
                />
              </div>
              <ProvenanceNote board={archived} n={reportCard.n} />
            </div>
          ) : (
            fieldSummary && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <SummaryTile label="Field" value={`${fieldSummary.size} players`} />
                {fieldSummary.sleeper && (
                  <SummaryTile
                    label="Sleeper"
                    value={`${fieldSummary.sleeper.player_name} · ${Math.round(fieldSummary.sleeper.top_20_prob * 100)}% Top 20 · ${Math.round(fieldSummary.sleeper.win_prob * 100)}% Win`}
                  />
                )}
                {coverage && <SummaryTile label="Coverage" value={coverage.value} title={coverage.title} />}
              </div>
            )
          )}

          {/* Controls */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search players…"
              className="w-full rounded-md border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-tertiary focus:border-accent focus:outline-none sm:w-72"
              aria-label="Search players"
            />
            <div className="flex items-center gap-3">
              {query.trim() && (
                <p className="text-xs text-fg-tertiary">
                  {rows.length} of {boardOutcomes.length} players
                </p>
              )}
              <button
                type="button"
                onClick={() =>
                  downloadBoardCsv(
                    `${(selectedTournament?.name ?? 'leaderboard')
                      .replace(/[^a-z0-9]+/gi, '-')
                      .toLowerCase()}-board.csv`,
                    rows,
                  )
                }
                className="shrink-0 rounded-md border bg-surface px-3 py-1.5 text-xs font-medium text-fg-secondary transition-colors hover:text-fg"
              >
                Export CSV
              </button>
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border">
            <div className="max-h-[70vh] overflow-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="sticky top-0 z-10">
                  <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                    <th className="px-4 py-3 w-12 text-right">#</th>
                    <th className="px-4 py-3">Player</th>
                    {isCompleted && <th className="px-4 py-3 text-right">Finish</th>}
                    {COLUMNS.map((col) => (
                      <th key={col.key} className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => toggleSort(col.key)}
                          className={`inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-fg ${
                            sortKey === col.key ? 'text-fg' : ''
                          }`}
                          aria-label={`Sort by ${col.label}`}
                          title={
                            col.key === 'win_prob'
                              ? "Win is intentionally de-emphasised. The board reads overall contention well but doesn't reliably single out one winner. Weigh a player's chances by Top 10, Top 20 and Make Cut instead."
                              : undefined
                          }
                        >
                          {col.label}
                          <span className="w-2 text-[0.6rem]">
                            {sortKey === col.key ? (sortDir === 'desc' ? '▼' : '▲') : ''}
                          </span>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {rows.map((o, idx) => (
                    <tr
                      key={o.player_id}
                      className={`transition-colors hover:bg-surface-2 ${
                        idx === 0 ? 'bg-surface-2/60' : 'bg-surface'
                      }`}
                    >
                      <td className="px-4 py-2.5 text-right font-mono text-fg-tertiary">{idx + 1}</td>
                      <td className="px-4 py-2.5 font-medium text-fg">
                        <button
                          type="button"
                          onClick={() => setSelectedPlayerId(o.player_id)}
                          className="text-left hover:text-accent hover:underline"
                        >
                          {o.player_name}
                        </button>
                      </td>
                      {isCompleted && (
                        <td
                          className={`px-4 py-2.5 text-right font-mono text-xs ${
                            o.final_position != null ? 'text-fg' : 'text-fg-tertiary'
                          }`}
                        >
                          {formatFinish(o)}
                        </td>
                      )}
                      {COLUMNS.map((col) => {
                        const value = o[col.key]
                        const max = colMax[col.key]
                        const width = max > 0 ? Math.max((value / max) * 100, 1.5) : 0
                        return (
                          <td key={col.key} className="px-4 py-2.5">
                            <div className="relative flex items-center justify-end">
                              <div
                                className={`pointer-events-none absolute inset-y-[3px] right-0 rounded-sm ${col.barClass}`}
                                style={{ width: `${width}%` }}
                              />
                              <span className={`relative z-[1] font-mono tabular-nums ${col.cellClass}`}>
                                {formatPct(value)}
                              </span>
                            </div>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {rows.length === 0 && query.trim() && (
            <p className="text-sm text-fg-tertiary">No players match “{query.trim()}”.</p>
          )}
        </>
      )}

      {selectedPlayerId != null && (
        <PlayerDrawer
          playerId={selectedPlayerId}
          outcome={drawerOutcome}
          tournamentName={selectedTournament?.name ?? null}
          board={isCompleted ? (archived?.available ? archived : null) : (predictions ?? null)}
          onClose={() => setSelectedPlayerId(null)}
        />
      )}
    </main>
  )
}
