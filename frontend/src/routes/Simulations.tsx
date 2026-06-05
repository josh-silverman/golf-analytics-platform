import { useCurrentTournament } from '../lib/api/tournaments'
import { useSimulation } from '../lib/api/simulations'

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

function formatScore(s: number): string {
  if (s === 0) return 'E'
  return s > 0 ? `+${s.toFixed(1)}` : s.toFixed(1)
}

export function Simulations() {
  const { data: currentTournament, isLoading: tournamentLoading } = useCurrentTournament()
  const tournamentId = currentTournament?.id ?? null
  const {
    data: simulation,
    isLoading: simLoading,
    isError,
    error,
  } = useSimulation(tournamentId)

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Simulation</h1>
        {currentTournament && (
          <p className="mt-1 text-sm text-fg-secondary">
            {currentTournament.name} ·{' '}
            {new Date(currentTournament.start_date).toLocaleDateString()}
          </p>
        )}
        {simulation && (
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-fg-tertiary">
            <span>
              Method:{' '}
              <span className="font-mono text-accent">Monte Carlo</span>
            </span>
            <span>
              Iterations:{' '}
              <span className="font-mono">
                {simulation.n_iterations.toLocaleString()}
              </span>
            </span>
            <span>
              Score σ: <span className="font-mono">{simulation.score_std.toFixed(1)} strokes</span>
            </span>
            <span>As of: {simulation.as_of}</span>
          </div>
        )}
        {simulation && (
          <p className="mt-2 text-xs text-fg-tertiary">
            Probabilities are derived from simulation, not direct classifier outputs —
            win ≤ top-5 ≤ top-10 ≤ make-cut by construction.
          </p>
        )}
      </header>

      {(tournamentLoading || simLoading) && (
        <p className="text-fg-secondary">Running simulation…</p>
      )}

      {!tournamentLoading && currentTournament == null && (
        <p className="text-fg-secondary">No active tournament to simulate.</p>
      )}

      {isError && (
        <p className="text-negative">
          Error: {error instanceof Error ? error.message : 'Unknown failure'}
        </p>
      )}

      {simulation && (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                <th className="w-10 px-4 py-3 text-right">#</th>
                <th className="px-4 py-3">Player</th>
                <th className="px-4 py-3 text-right">Skill (exp. score/rnd)</th>
                <th className="px-4 py-3 text-right">Win</th>
                <th className="px-4 py-3 text-right">Top 5</th>
                <th className="px-4 py-3 text-right">Top 10</th>
                <th className="px-4 py-3 text-right">Top 20</th>
                <th className="px-4 py-3 text-right">Make Cut</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {simulation.outcomes.map((o, idx) => (
                <tr
                  key={o.player_id}
                  className="bg-surface transition-colors hover:bg-surface-2"
                >
                  <td className="px-4 py-3 text-right font-mono text-fg-tertiary">
                    {idx + 1}
                  </td>
                  <td className="px-4 py-3 font-medium text-fg">{o.player_name}</td>
                  <td
                    className={`px-4 py-3 text-right font-mono tabular-nums ${
                      o.expected_score < 0 ? 'text-positive' : 'text-negative'
                    }`}
                  >
                    {formatScore(o.expected_score)}
                  </td>
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
