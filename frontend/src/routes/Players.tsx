import { Link } from 'react-router'

import { usePlayers } from '../lib/api/players'

export function Players() {
  const { data, isLoading, isError, error } = usePlayers()

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Players</h1>
        {data && (
          <p className="mt-1 text-sm text-fg-tertiary">
            {data.page.total?.toLocaleString() ?? data.data.length} players · source:{' '}
            {data.meta.source} · click a row to view SG trends
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
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Country</th>
                <th className="px-4 py-3">Turned Pro</th>
                <th className="px-4 py-3 text-right">DG ID</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.data.map((player) => (
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
      )}
    </main>
  )
}
