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

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Tournaments</h1>
        {data && (
          <p className="mt-1 text-sm text-fg-tertiary">
            {data.page.total?.toLocaleString() ?? data.data.length} events · source:{' '}
            {data.meta.source}
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
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                <th className="px-4 py-3">Tournament</th>
                <th className="px-4 py-3">Season</th>
                <th className="px-4 py-3">Dates</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Purse</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.data.map((t) => (
                <tr key={t.id} className="bg-surface hover:bg-surface-2 transition-colors">
                  <td className="px-4 py-3 font-medium text-fg">{t.name}</td>
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
      )}
    </main>
  )
}
