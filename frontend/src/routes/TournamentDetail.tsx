/**
 * TournamentDetail — shows a tournament's field, entry count, and links to
 * predictions and simulation for that event.
 *
 * Data comes from three existing endpoints:
 *   GET /api/v1/tournaments/{id}        — basic info
 *   GET /api/v1/predictions/{id}        — ML probability leaderboard
 *   GET /api/v1/simulations/{id}        — MC simulation outcomes
 */

import { Link, useParams } from 'react-router'

import { usePredictions } from '../lib/api/predictions'
import { useSimulation } from '../lib/api/simulations'
import { useTournament } from '../lib/api/tournaments'

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

function formatPurse(cents: number | null): string {
  if (cents == null) return '—'
  return `$${(cents / 1_000_000).toFixed(1)}M`
}

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

const STATUS_COLOR: Record<string, string> = {
  upcoming: 'text-warning',
  in_progress: 'text-positive',
  completed: 'text-fg-tertiary',
}

export function TournamentDetail() {
  const { id } = useParams<{ id: string }>()
  const tournamentId = Number(id)

  const { data: tournamentEnv, isLoading: tLoading, isError: tError } = useTournament(tournamentId)
  const { data: predictions, isLoading: pLoading } = usePredictions(tournamentId)
  const { data: simulation, isLoading: sLoading } = useSimulation(tournamentId)

  const tournament = tournamentEnv?.data

  if (tLoading) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-10">
        <p className="text-fg-secondary">Loading…</p>
      </main>
    )
  }

  if (tError || !tournament) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-10">
        <p className="text-negative">Tournament not found.</p>
        <Link to="/tournaments" className="mt-4 inline-block text-sm text-accent hover:underline">
          ← Back to tournaments
        </Link>
      </main>
    )
  }

  return (
    <main className="mx-auto max-w-6xl space-y-8 px-6 py-10">
      {/* Back link */}
      <Link to="/tournaments" className="text-sm text-fg-secondary hover:text-fg">
        ← Tournaments
      </Link>

      {/* Header */}
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{tournament.name}</h1>
        <div className="flex flex-wrap gap-4 text-sm text-fg-secondary">
          <span>Season {tournament.season}</span>
          <span>{formatDate(tournament.start_date)}</span>
          <span
            className={`font-medium capitalize ${STATUS_COLOR[tournament.status] ?? 'text-fg-secondary'}`}
          >
            {tournament.status.replace('_', ' ')}
          </span>
          <span>Purse: {formatPurse(tournament.purse)}</span>
        </div>
      </header>

      {/* Quick-link cards to analysis pages */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Link
          to={`/leaderboard`}
          className="group rounded-lg border bg-surface p-5 transition-colors hover:border-accent"
        >
          <p className="text-xs uppercase tracking-wider text-fg-tertiary">ML Predictions</p>
          <p className="mt-1 text-base font-medium text-fg group-hover:text-accent">
            Prediction Leaderboard
          </p>
          {pLoading && (
            <p className="mt-1 text-xs text-fg-tertiary">Loading…</p>
          )}
          {predictions && (
            <p className="mt-1 text-xs text-fg-tertiary">
              {predictions.outcomes.length} players · model{' '}
              <span className="font-mono">{predictions.model_name}</span>
            </p>
          )}
        </Link>

        <Link
          to={`/simulations`}
          className="group rounded-lg border bg-surface p-5 transition-colors hover:border-accent"
        >
          <p className="text-xs uppercase tracking-wider text-fg-tertiary">Monte Carlo</p>
          <p className="mt-1 text-base font-medium text-fg group-hover:text-accent">
            Simulation Outcomes
          </p>
          {sLoading && (
            <p className="mt-1 text-xs text-fg-tertiary">Loading…</p>
          )}
          {simulation && (
            <p className="mt-1 text-xs text-fg-tertiary">
              {simulation.n_iterations.toLocaleString()} iterations ·{' '}
              {simulation.outcomes.length} players
            </p>
          )}
        </Link>
      </section>

      {/* Top-5 predictions preview */}
      {predictions && predictions.outcomes.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">Top Predictions</h2>
            <Link to="/leaderboard" className="text-xs text-accent hover:underline">
              Full leaderboard →
            </Link>
          </div>
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                  <th className="w-10 px-4 py-3 text-right">#</th>
                  <th className="px-4 py-3">Player</th>
                  <th className="px-4 py-3 text-right">Win</th>
                  <th className="px-4 py-3 text-right">Top 5</th>
                  <th className="px-4 py-3 text-right">Top 10</th>
                  <th className="px-4 py-3 text-right">Make Cut</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {predictions.outcomes.slice(0, 10).map((o, idx) => (
                  <tr key={o.player_id} className="bg-surface transition-colors hover:bg-surface-2">
                    <td className="px-4 py-2 text-right font-mono text-fg-tertiary">{idx + 1}</td>
                    <td className="px-4 py-2 font-medium text-fg">{o.player_name}</td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums text-accent">
                      {formatPct(o.win_prob)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums text-fg">
                      {formatPct(o.top_5_prob)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums text-fg">
                      {formatPct(o.top_10_prob)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums text-fg-secondary">
                      {formatPct(o.make_cut_prob)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Top-5 MC simulation preview */}
      {simulation && simulation.outcomes.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">Monte Carlo Win Probabilities</h2>
            <Link to="/simulations" className="text-xs text-accent hover:underline">
              Full simulation →
            </Link>
          </div>
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                  <th className="w-10 px-4 py-3 text-right">#</th>
                  <th className="px-4 py-3">Player</th>
                  <th className="px-4 py-3 text-right">Win</th>
                  <th className="px-4 py-3 text-right">Top 5</th>
                  <th className="px-4 py-3 text-right">Skill</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {simulation.outcomes.slice(0, 10).map((o, idx) => (
                  <tr key={o.player_id} className="bg-surface transition-colors hover:bg-surface-2">
                    <td className="px-4 py-2 text-right font-mono text-fg-tertiary">{idx + 1}</td>
                    <td className="px-4 py-2 font-medium text-fg">{o.player_name}</td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums text-accent">
                      {formatPct(o.win_prob)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums text-fg">
                      {formatPct(o.top_5_prob)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right font-mono tabular-nums ${
                        o.expected_score < 0 ? 'text-positive' : 'text-negative'
                      }`}
                    >
                      {o.expected_score >= 0 ? '+' : ''}
                      {o.expected_score.toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  )
}
