/**
 * PlayerDetail — per-player profile: current-event model outlook plus the
 * shared strokes-gained trends (sparklines, averages, recent rounds).
 */

import { Link, useParams } from 'react-router'

import { PlayerSGTrends } from '../components/PlayerSGTrends'
import { usePlayer, useRecentRounds } from '../lib/api/players'
import { usePredictions } from '../lib/api/predictions'
import { useCurrentTournament } from '../lib/api/tournaments'

// Same honest emphasis as the leaderboard: Win de-emphasised, Top 20 highlighted.
type ProbKey = 'win_prob' | 'top_5_prob' | 'top_10_prob' | 'top_20_prob' | 'make_cut_prob'

const OUTLOOK_MARKETS: { key: ProbKey; label: string; valueClass: string }[] = [
  { key: 'win_prob', label: 'Win', valueClass: 'text-fg-tertiary' },
  { key: 'top_5_prob', label: 'Top 5', valueClass: 'text-fg' },
  { key: 'top_10_prob', label: 'Top 10', valueClass: 'text-fg' },
  { key: 'top_20_prob', label: 'Top 20', valueClass: 'text-accent' },
  { key: 'make_cut_prob', label: 'Make Cut', valueClass: 'text-fg-secondary' },
]

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

export function PlayerDetail() {
  const { id } = useParams<{ id: string }>()
  const playerId = Number(id)

  const { data: playerEnv, isLoading: playerLoading, isError: playerError } = usePlayer(playerId)
  const { data: roundsEnv, isLoading: roundsLoading } = useRecentRounds(playerId)

  const { data: currentTournament } = useCurrentTournament()
  const { data: predictions } = usePredictions(currentTournament?.id ?? null)
  const outlook = predictions?.outcomes.find((o) => o.player_id === playerId) ?? null

  const player = playerEnv?.data
  // API returns most-recent first; reverse so charts read oldest → newest.
  const rounds = roundsEnv ? [...roundsEnv.data].reverse() : []

  if (playerLoading || roundsLoading) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-10">
        <p className="text-fg-secondary">Loading…</p>
      </main>
    )
  }

  if (playerError || !player) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-10">
        <p className="text-negative">Player not found.</p>
        <Link to="/players" className="mt-4 inline-block text-sm text-accent hover:underline">
          ← Back to players
        </Link>
      </main>
    )
  }

  return (
    <main className="mx-auto max-w-6xl space-y-8 px-6 py-10">
      <Link to="/players" className="text-sm text-fg-secondary hover:text-fg">
        ← Players
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{player.full_name}</h1>
        <div className="mt-1 flex flex-wrap gap-4 text-sm text-fg-secondary">
          <span>
            Country: <span className="font-mono text-fg">{player.country}</span>
          </span>
          {player.turned_pro && (
            <span>
              Turned pro: <span className="font-mono text-fg">{player.turned_pro}</span>
            </span>
          )}
          {player.dg_id && (
            <span>
              DG ID: <span className="font-mono text-fg-tertiary">{player.dg_id}</span>
            </span>
          )}
          <span>{rounds.length} rounds loaded</span>
        </div>
      </header>

      {/* Current-event model outlook */}
      {currentTournament && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-base font-semibold">Current Event Outlook</h2>
            <Link to="/leaderboard" className="text-xs text-accent hover:underline">
              {currentTournament.name} →
            </Link>
          </div>
          {outlook ? (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                {OUTLOOK_MARKETS.map((m) => (
                  <div key={m.key} className="rounded-lg border bg-surface p-3">
                    <p className="text-xs uppercase tracking-wider text-fg-tertiary">{m.label}</p>
                    <p className={`mt-1 font-mono text-lg font-semibold tabular-nums ${m.valueClass}`}>
                      {formatPct(outlook[m.key])}
                    </p>
                  </div>
                ))}
              </div>
              <p className="text-xs text-fg-tertiary">
                From the active model
                {predictions?.model_version_id ? (
                  <> (<span className="font-mono">{predictions.model_name}</span>)</>
                ) : null}
                . Top 20 and Make Cut are the most reliable markets; Win is intentionally coarse.
              </p>
            </>
          ) : (
            <p className="text-sm text-fg-tertiary">Not in the field for {currentTournament.name}.</p>
          )}
        </section>
      )}

      <PlayerSGTrends rounds={rounds} />
    </main>
  )
}
