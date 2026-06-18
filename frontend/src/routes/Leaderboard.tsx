import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'

import { PlayerDrawer } from '../components/PlayerDrawer'
import { usePredictions, type PlayerOutcome } from '../lib/api/predictions'
import { useTrackRecord } from '../lib/api/trackRecord'
import { useCurrentTournament, useTournaments } from '../lib/api/tournaments'
import type { Tournament } from '../lib/api/types'

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

function formatFinish(o: PlayerOutcome): string {
  if (o.final_position != null) return `${o.final_position}`
  if (o.made_cut === false) return 'MC'
  return '—'
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

// Combined label + value in a single text node on purpose, so the player name
// never appears as its own element (keeps it out of exact-text test queries).
function SummaryTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-surface px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-fg-tertiary">{label}</p>
      <p className="mt-0.5 truncate text-sm text-fg">{value}</p>
    </div>
  )
}

export function Leaderboard() {
  const { data: currentTournament, isLoading: currentLoading } = useCurrentTournament()
  const { data: tournamentsEnv } = useTournaments()
  const { data: trackRecord } = useTrackRecord()
  const [searchParams, setSearchParams] = useSearchParams()

  // Selected event: an explicit pick overrides; otherwise follow the current
  // event. Seeded from the URL so a board is shareable/bookmarkable.
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const e = searchParams.get('event')
    return e ? Number(e) : null
  })
  const effectiveId = selectedId ?? currentTournament?.id ?? null

  const {
    data: predictions,
    isLoading: predictionsLoading,
    isError,
    error,
  } = usePredictions(effectiveId)

  // Event options for the switcher; falls back to just the current event when
  // the full list isn't available.
  const eventOptions = useMemo(() => {
    const list = Array.isArray(tournamentsEnv?.data)
      ? tournamentsEnv.data
      : currentTournament
        ? [currentTournament]
        : []
    return [...list].sort((a, b) => {
      const sa = _STATUS_ORDER[a.status] ?? 9
      const sb = _STATUS_ORDER[b.status] ?? 9
      if (sa !== sb) return sa - sb
      const ta = +new Date(a.start_date)
      const tb = +new Date(b.start_date)
      return a.status === 'upcoming' ? ta - tb : tb - ta
    })
  }, [tournamentsEnv, currentTournament])

  const selectedTournament =
    eventOptions.find((t) => t.id === effectiveId) ?? currentTournament ?? null

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
    if (predictions) {
      for (const o of predictions.outcomes) {
        for (const c of COLUMNS) m[c.key] = Math.max(m[c.key], o[c.key])
      }
    }
    return m
  }, [predictions])

  const rows = useMemo(() => {
    if (!predictions) return []
    const q = query.trim().toLowerCase()
    const filtered = q
      ? predictions.outcomes.filter((o) => o.player_name.toLowerCase().includes(q))
      : predictions.outcomes
    return [...filtered].sort((a, b) => {
      const diff = a[sortKey] - b[sortKey]
      return sortDir === 'desc' ? -diff : diff
    })
  }, [predictions, sortKey, sortDir, query])

  const drawerOutcome =
    predictions?.outcomes.find((o) => o.player_id === selectedPlayerId) ?? null

  // At-a-glance leaders, computed from the already-loaded field.
  const fieldSummary = useMemo(() => {
    const o = predictions?.outcomes ?? []
    if (o.length === 0) return null
    const top = (k: SortKey) => o.reduce((best, c) => (c[k] > best[k] ? c : best), o[0])
    return {
      favorite: top('win_prob'),
      contender: top('top_20_prob'),
      safestCut: top('make_cut_prob'),
      size: o.length,
    }
  }, [predictions])

  const isCompleted = selectedTournament?.status === 'completed'

  // Model report card: how the pre-event board compared to the actual result.
  const reportCard = useMemo(() => {
    if (!predictions || !isCompleted) return null
    const o = predictions.outcomes
    if (!o.some((x) => x.final_position != null || x.made_cut != null)) return null
    const winner = o.find((x) => x.final_position === 1) ?? null
    const byWin = [...o].sort((a, b) => b.win_prob - a.win_prob)
    const winnerRank = winner
      ? byWin.findIndex((x) => x.player_id === winner.player_id) + 1
      : null
    const modelTop20 = [...o].sort((a, b) => b.top_20_prob - a.top_20_prob).slice(0, 20)
    const top20Hits = modelTop20.filter(
      (x) => x.final_position != null && x.final_position <= 20,
    ).length
    const cutGraded = o.filter((x) => x.made_cut != null)
    const cutCorrect = cutGraded.filter((x) => (x.make_cut_prob >= 0.5) === x.made_cut).length
    const cutAcc = cutGraded.length ? cutCorrect / cutGraded.length : null
    return { winner, winnerRank, top20Hits, cutAcc }
  }, [predictions, isCompleted])

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

        {predictions && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-tertiary">
            <span>
              Model: <span className="font-mono text-fg-secondary">{predictions.model_name}</span>
            </span>
            <span>
              Version:{' '}
              {predictions.model_version_id ? (
                <span className="font-mono text-fg-secondary">{predictions.model_version_id}</span>
              ) : (
                <span className="text-warning">fallback (no trained model registered)</span>
              )}
            </span>
            <span>
              Features:{' '}
              <span className="font-mono text-fg-secondary">
                {predictions.feature_set_hash.slice(0, 12)}
              </span>
            </span>
            <span>As of: {predictions.as_of}</span>
          </div>
        )}

        {predictions && (
          <p className="text-xs italic text-fg-tertiary">
            Pre-event predictions — not updated during play.
          </p>
        )}

        {trackRecord?.available && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-tertiary">
            <span className="font-medium text-fg-secondary">
              Track record (last {trackRecord.events} events):
            </span>
            <span>
              winner in top-10{' '}
              <span className="font-mono text-fg-secondary">
                {formatPct(trackRecord.winner_in_top10_rate)}
              </span>
            </span>
            <span>
              · top-20 hit rate{' '}
              <span className="font-mono text-accent">
                {formatPct(trackRecord.avg_top20_hit_rate)}
              </span>
            </span>
            <span>
              · make-cut accuracy{' '}
              <span className="font-mono text-accent">
                {formatPct(trackRecord.make_cut_accuracy)}
              </span>
            </span>
            <span>
              · avg winner rank{' '}
              <span className="font-mono text-fg-secondary">
                {trackRecord.mean_winner_rank.toFixed(0)}
              </span>
            </span>
          </div>
        )}
      </header>

      {(currentLoading || predictionsLoading) && (
        <div className="space-y-1">
          <p className="text-fg-secondary">Loading predictions…</p>
          <p className="text-xs text-fg-tertiary">
            The first load after a while warms live tour data from DataGolf and can take a
            minute — it&rsquo;s fast afterwards.
          </p>
        </div>
      )}

      {!currentLoading && effectiveId == null && (
        <p className="text-fg-secondary">No active tournament to predict.</p>
      )}

      {isError && (
        <p className="text-negative">
          Error: {error instanceof Error ? error.message : 'Unknown failure'}
        </p>
      )}

      {predictions && (
        <>
          {/* How to read this board — reflects the model's real strengths. */}
          <div className="rounded-lg border border-border/70 bg-surface px-4 py-3 text-xs leading-relaxed text-fg-secondary">
            <span className="font-medium text-fg">How to read this board.</span>{' '}
            Sorted by <span className="text-accent">Top 20</span> — the model's most reliable
            market (make-cut and top-20 carry genuine skill). <span className="text-fg">Win</span>{' '}
            is intentionally de-emphasised: the model does not sharply separate a single winner, so
            read contention through Top 10 / Top 20 / Make Cut rather than the Win column. Click a
            column header to re-sort, or a player to see their strokes-gained trends.
          </div>

          {/* Completed event → model report card; otherwise field at-a-glance */}
          {isCompleted && reportCard ? (
            <div className="space-y-2">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <SummaryTile
                  label="Winner"
                  value={
                    reportCard.winner
                      ? `${reportCard.winner.player_name} · model #${reportCard.winnerRank} by win%`
                      : '—'
                  }
                />
                <SummaryTile label="Top-20 hits" value={`${reportCard.top20Hits} / 20`} />
                <SummaryTile
                  label="Make-cut accuracy"
                  value={reportCard.cutAcc != null ? formatPct(reportCard.cutAcc) : '—'}
                />
              </div>
              <p className="text-xs text-fg-tertiary">
                Report card — the model&rsquo;s pre-event board vs. what actually happened. The
                Finish column shows where each player ended up (MC = missed cut).
              </p>
            </div>
          ) : (
            fieldSummary && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <SummaryTile
                  label="Favorite"
                  value={`${fieldSummary.favorite.player_name} · ${formatPct(fieldSummary.favorite.win_prob)}`}
                />
                <SummaryTile
                  label="Top contender"
                  value={`${fieldSummary.contender.player_name} · ${formatPct(fieldSummary.contender.top_20_prob)}`}
                />
                <SummaryTile
                  label="Safest cut"
                  value={`${fieldSummary.safestCut.player_name} · ${formatPct(fieldSummary.safestCut.make_cut_prob)}`}
                />
                <SummaryTile label="Field" value={`${fieldSummary.size} players`} />
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
              <p className="text-xs text-fg-tertiary">
                {query.trim()
                  ? `${rows.length} of ${predictions.outcomes.length} players`
                  : `${predictions.outcomes.length} players`}
              </p>
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
                              ? 'Win probabilities are intentionally coarse — use Top 20 and Make Cut for the most reliable signal.'
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
          onClose={() => setSelectedPlayerId(null)}
        />
      )}
    </main>
  )
}
