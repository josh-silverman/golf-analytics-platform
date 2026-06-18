import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { useCurrentTournament } from '../lib/api/tournaments'
import { usePredictions } from '../lib/api/predictions'

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

type SortKey =
  | 'win_prob'
  | 'top_5_prob'
  | 'top_10_prob'
  | 'top_20_prob'
  | 'make_cut_prob'

// Per-column config so the header and body stay in sync. ``cellClass`` carries
// the per-column emphasis (Win is de-emphasised — the model does not sharply
// separate a single winner; Top 20 is highlighted as the most reliable market).
const COLUMNS: {
  key: SortKey
  label: string
  cellClass: string
  barClass: string
}[] = [
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

export function Leaderboard() {
  const { data: currentTournament, isLoading: tournamentLoading } = useCurrentTournament()
  const tournamentId = currentTournament?.id ?? null
  const {
    data: predictions,
    isLoading: predictionsLoading,
    isError,
    error,
  } = usePredictions(tournamentId)

  // Default sort: Top 20 descending — the most reliable market, not Win.
  const [sortKey, setSortKey] = useState<SortKey>('top_20_prob')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [query, setQuery] = useState('')

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

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header className="space-y-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Leaderboard</h1>
          {currentTournament && (
            <span
              className={`rounded-full px-2 py-0.5 text-[0.65rem] font-medium uppercase tracking-wider ${
                STATUS_BADGE[currentTournament.status] ?? 'bg-fg-tertiary/15 text-fg-tertiary'
              }`}
            >
              {currentTournament.status.replace('_', ' ')}
            </span>
          )}
        </div>

        {currentTournament && (
          <p className="text-sm text-fg-secondary">
            {currentTournament.name} ·{' '}
            {new Date(currentTournament.start_date).toLocaleDateString(undefined, {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
            })}
            {predictions && (
              <span className="text-fg-tertiary"> · {predictions.outcomes.length} players</span>
            )}
          </p>
        )}

        {predictions && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-tertiary">
            <span>Model: <span className="font-mono text-fg-secondary">{predictions.model_name}</span></span>
            <span>
              Version:{' '}
              {predictions.model_version_id ? (
                <span className="font-mono text-fg-secondary">{predictions.model_version_id}</span>
              ) : (
                <span className="text-warning">fallback (no trained model registered)</span>
              )}
            </span>
            <span>
              Features: <span className="font-mono text-fg-secondary">{predictions.feature_set_hash.slice(0, 12)}</span>
            </span>
            <span>As of: {predictions.as_of}</span>
          </div>
        )}
      </header>

      {(tournamentLoading || predictionsLoading) && (
        <div className="space-y-1">
          <p className="text-fg-secondary">Loading predictions…</p>
          <p className="text-xs text-fg-tertiary">
            The first load after a while warms live tour data from DataGolf and can take a
            minute — it&rsquo;s fast afterwards.
          </p>
        </div>
      )}

      {!tournamentLoading && currentTournament == null && (
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
            read contention through Top 10 / Top 20 / Make Cut rather than the Win column. Click any
            column header to re-sort.
          </div>

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
            <p className="text-xs text-fg-tertiary">
              {query.trim()
                ? `${rows.length} of ${predictions.outcomes.length} players`
                : `${predictions.outcomes.length} players`}
            </p>
          </div>

          <div className="overflow-hidden rounded-lg border">
            <div className="max-h-[70vh] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10">
                  <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                    <th className="px-4 py-3 w-12 text-right">#</th>
                    <th className="px-4 py-3">Player</th>
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
                      <td className="px-4 py-2.5 text-right font-mono text-fg-tertiary">
                        {idx + 1}
                      </td>
                      <td className="px-4 py-2.5 font-medium text-fg">
                        <Link
                          to={`/players/${o.player_id}`}
                          className="hover:text-accent hover:underline"
                        >
                          {o.player_name}
                        </Link>
                      </td>
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
                              <span
                                className={`relative z-[1] font-mono tabular-nums ${col.cellClass}`}
                              >
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
            <p className="text-sm text-fg-tertiary">
              No players match “{query.trim()}”.
            </p>
          )}
        </>
      )}
    </main>
  )
}
