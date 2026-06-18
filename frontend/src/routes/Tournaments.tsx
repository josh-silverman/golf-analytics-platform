import { useMemo, useState } from 'react'
import { Link } from 'react-router'

import { useTournaments } from '../lib/api/tournaments'
import type { Tournament } from '../lib/api/types'

const STATUS_LABEL: Record<Tournament['status'], string> = {
  upcoming: 'Upcoming',
  in_progress: 'In Progress',
  completed: 'Completed',
}

const STATUS_CLASS: Record<Tournament['status'], string> = {
  upcoming: 'text-warning',
  in_progress: 'text-positive',
  completed: 'text-fg-tertiary',
}

// Filter chips, in chronological-relevance order. Labels carry a count so they
// never collide with the bare status text rendered in the table cells.
const STATUS_FILTERS: ('all' | Tournament['status'])[] = [
  'all',
  'upcoming',
  'in_progress',
  'completed',
]

const FILTER_LABEL: Record<'all' | Tournament['status'], string> = {
  all: 'All',
  upcoming: 'Upcoming',
  in_progress: 'In Progress',
  completed: 'Completed',
}

function formatPurse(cents: number | null): string {
  if (cents == null) return '—'
  const m = cents / 1_000_000
  return m >= 1 ? `$${m.toFixed(1)}M` : `$${(cents / 1_000).toFixed(0)}K`
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function Tournaments() {
  const { data, isLoading, isError, error } = useTournaments()
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<'all' | Tournament['status']>('all')

  const counts = useMemo(() => {
    const c = { all: 0, upcoming: 0, in_progress: 0, completed: 0 }
    if (data) {
      c.all = data.data.length
      for (const t of data.data) c[t.status] += 1
    }
    return c
  }, [data])

  const filtered = useMemo(() => {
    if (!data) return []
    const q = query.trim().toLowerCase()
    return data.data.filter(
      (t) =>
        (status === 'all' || t.status === status) &&
        (!q || t.name.toLowerCase().includes(q)),
    )
  }, [data, query, status])

  const total = data?.page.total ?? data?.data.length ?? 0
  const filtering = query.trim() !== '' || status !== 'all'

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Tournaments</h1>
        {data && (
          <p className="mt-1 text-sm text-fg-tertiary">
            {total.toLocaleString()} events · source: {data.meta.source}
          </p>
        )}
      </header>

      {isLoading && <p className="text-fg-secondary">Loading…</p>}

      {isError && (
        <p className="text-negative">
          Error: {error instanceof Error ? error.message : 'Unknown failure'}
        </p>
      )}

      {data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search tournaments…"
                className="w-full rounded-md border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-tertiary focus:border-accent focus:outline-none sm:w-64"
                aria-label="Search tournaments"
              />
              <div className="flex flex-wrap gap-1.5">
                {STATUS_FILTERS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStatus(s)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                      status === s
                        ? 'bg-accent text-white'
                        : 'border bg-surface text-fg-secondary hover:text-fg'
                    }`}
                  >
                    {FILTER_LABEL[s]} ({counts[s].toLocaleString()})
                  </button>
                ))}
              </div>
            </div>
            {filtering && (
              <p className="text-xs text-fg-tertiary">
                Showing {filtered.length.toLocaleString()} of {data.data.length.toLocaleString()}
              </p>
            )}
          </div>

          <div className="overflow-hidden rounded-lg border">
            <div className="max-h-[70vh] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10">
                  <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                    <th className="px-4 py-3">Tournament</th>
                    <th className="px-4 py-3">Season</th>
                    <th className="px-4 py-3">Dates</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Purse</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filtered.map((t) => (
                    <tr key={t.id} className="bg-surface hover:bg-surface-2 transition-colors">
                      <td className="px-4 py-3 font-medium text-fg">
                        <Link to={`/tournaments/${t.id}`} className="hover:text-accent hover:underline">
                          {t.name}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-fg-secondary">{t.season}</td>
                      <td className="px-4 py-3 text-fg-secondary">
                        {formatDate(t.start_date)} – {formatDate(t.end_date)}
                      </td>
                      <td className={`px-4 py-3 font-medium ${STATUS_CLASS[t.status]}`}>
                        {STATUS_LABEL[t.status]}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-fg-secondary">
                        {formatPurse(t.purse)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {filtered.length === 0 && filtering && (
            <p className="text-sm text-fg-tertiary">No tournaments match your filters.</p>
          )}
        </>
      )}
    </main>
  )
}
