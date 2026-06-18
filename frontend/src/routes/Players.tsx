import { useMemo, useState } from 'react'
import { Link } from 'react-router'

import { usePlayers } from '../lib/api/players'

// The registry is ~3,500 players; render a capped slice for snappy scrolling
// while search still filters across the entire list.
const DISPLAY_CAP = 200

export function Players() {
  const { data, isLoading, isError, error } = usePlayers()
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    if (!data) return []
    const q = query.trim().toLowerCase()
    if (!q) return data.data
    return data.data.filter(
      (p) =>
        p.full_name.toLowerCase().includes(q) ||
        (p.country ?? '').toLowerCase().includes(q),
    )
  }, [data, query])

  const total = data?.page.total ?? data?.data.length ?? 0
  const displayed = filtered.slice(0, DISPLAY_CAP)
  const overflow = filtered.length > DISPLAY_CAP

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Players</h1>
        {data && (
          <p className="mt-1 text-sm text-fg-tertiary">
            {total.toLocaleString()} players · source: {data.meta.source} · click a row to view
            SG trends
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
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search players or country…"
              className="w-full rounded-md border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-tertiary focus:border-accent focus:outline-none sm:w-80"
              aria-label="Search players"
            />
            <p className="text-xs text-fg-tertiary">
              {query.trim()
                ? `${filtered.length.toLocaleString()} match${filtered.length === 1 ? '' : 'es'}`
                : `Search the full ${data.data.length.toLocaleString()}-player registry by name or country`}
              {overflow ? ` · showing first ${DISPLAY_CAP}` : ''}
            </p>
          </div>

          <div className="overflow-hidden rounded-lg border">
            <div className="max-h-[70vh] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10">
                  <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Country</th>
                    <th className="px-4 py-3">Turned Pro</th>
                    <th className="px-4 py-3 text-right">DG ID</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {displayed.map((player) => (
                    <tr key={player.id} className="bg-surface transition-colors hover:bg-surface-2">
                      <td className="px-4 py-3 font-medium text-fg">
                        <Link
                          to={`/players/${player.id}`}
                          className="hover:text-accent hover:underline"
                        >
                          {player.full_name}
                        </Link>
                      </td>
                      <td className="px-4 py-3 font-mono text-fg-secondary">{player.country}</td>
                      <td className="px-4 py-3 text-fg-secondary">{player.turned_pro ?? '—'}</td>
                      <td className="px-4 py-3 text-right font-mono text-fg-tertiary">
                        {player.dg_id ?? '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {filtered.length === 0 && query.trim() && (
            <p className="text-sm text-fg-tertiary">No players match “{query.trim()}”.</p>
          )}
        </>
      )}
    </main>
  )
}
