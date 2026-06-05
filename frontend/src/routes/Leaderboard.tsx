import { useCurrentTournament } from '../lib/api/tournaments'
import { usePredictions } from '../lib/api/predictions'

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
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

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Leaderboard</h1>
        {currentTournament && (
          <p className="mt-1 text-sm text-fg-secondary">
            {currentTournament.name} · {new Date(currentTournament.start_date).toLocaleDateString()}
          </p>
        )}
        {predictions && (
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-fg-tertiary">
            <span>Model: <span className="font-mono">{predictions.model_name}</span></span>
            <span>
              Version:{' '}
              {predictions.model_version_id ? (
                <span className="font-mono">{predictions.model_version_id}</span>
              ) : (
                <span className="text-warning">fallback (no trained model registered)</span>
              )}
            </span>
            <span>
              Features: <span className="font-mono">{predictions.feature_set_hash.slice(0, 12)}</span>
            </span>
            <span>As of: {predictions.as_of}</span>
          </div>
        )}
      </header>

      {(tournamentLoading || predictionsLoading) && (
        <p className="text-fg-secondary">Loading predictions…</p>
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
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                <th className="px-4 py-3 w-10 text-right">#</th>
                <th className="px-4 py-3">Player</th>
                <th className="px-4 py-3 text-right">Win</th>
                <th className="px-4 py-3 text-right">Top 5</th>
                <th className="px-4 py-3 text-right">Top 10</th>
                <th className="px-4 py-3 text-right">Top 20</th>
                <th className="px-4 py-3 text-right">Make Cut</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {predictions.outcomes.map((o, idx) => (
                <tr
                  key={o.player_id}
                  className="bg-surface hover:bg-surface-2 transition-colors"
                >
                  <td className="px-4 py-3 text-right font-mono text-fg-tertiary">
                    {idx + 1}
                  </td>
                  <td className="px-4 py-3 font-medium text-fg">{o.player_name}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-accent">
                    {formatPct(o.win_prob)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-fg">
                    {formatPct(o.top_5_prob)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-fg">
                    {formatPct(o.top_10_prob)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-fg-secondary">
                    {formatPct(o.top_20_prob)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-fg-secondary">
                    {formatPct(o.make_cut_prob)}
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
