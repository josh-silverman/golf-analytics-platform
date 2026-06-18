/**
 * TournamentDetail — shows a tournament's field, entry count, and links to
 * predictions for that event.
 *
 * Data comes from two endpoints:
 *   GET /api/v1/tournaments/{id}        — basic info
 *   GET /api/v1/predictions/{id}        — ML probability leaderboard
 */

import { useMemo } from 'react'
import { Link, useParams } from 'react-router'

import { usePredictions } from '../lib/api/predictions'
import { useTournament } from '../lib/api/tournaments'

type ProbKey =
  | 'win_prob'
  | 'top_5_prob'
  | 'top_10_prob'
  | 'top_20_prob'
  | 'make_cut_prob'

// Same column emphasis as the full Leaderboard: Win de-emphasised (the model
// doesn't sharply pick one winner), Top 20 highlighted as the reliable market.
const PREVIEW_COLUMNS: {
  key: ProbKey
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

  const tournament = tournamentEnv?.data

  // Top-10 preview sorted by Top 20 (the reliable market), with per-market
  // maxima so the inline bars scale to the field leader.
  const previewRows = useMemo(() => {
    if (!predictions) return []
    return [...predictions.outcomes]
      .sort((a, b) => b.top_20_prob - a.top_20_prob)
      .slice(0, 10)
  }, [predictions])

  const colMax = useMemo(() => {
    const m: Record<ProbKey, number> = {
      win_prob: 0,
      top_5_prob: 0,
      top_10_prob: 0,
      top_20_prob: 0,
      make_cut_prob: 0,
    }
    if (predictions) {
      for (const o of predictions.outcomes) {
        for (const c of PREVIEW_COLUMNS) m[c.key] = Math.max(m[c.key], o[c.key])
      }
    }
    return m
  }, [predictions])

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

      {/* Quick-link card to prediction leaderboard */}
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
      </section>

      {/* Top predictions preview — sorted by Top 20 (most reliable market) */}
      {predictions && previewRows.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">Top Predictions</h2>
            <Link to="/leaderboard" className="text-xs text-accent hover:underline">
              Full leaderboard →
            </Link>
          </div>
          <p className="text-xs text-fg-tertiary">
            Ranked by Top 20 — the model's most reliable market. Win is de-emphasised.
          </p>
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                  <th className="w-10 px-4 py-3 text-right">#</th>
                  <th className="px-4 py-3">Player</th>
                  {PREVIEW_COLUMNS.map((col) => (
                    <th key={col.key} className="px-4 py-3 text-right">
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {previewRows.map((o, idx) => (
                  <tr key={o.player_id} className="bg-surface transition-colors hover:bg-surface-2">
                    <td className="px-4 py-2 text-right font-mono text-fg-tertiary">{idx + 1}</td>
                    <td className="px-4 py-2 font-medium text-fg">{o.player_name}</td>
                    {PREVIEW_COLUMNS.map((col) => {
                      const value = o[col.key]
                      const max = colMax[col.key]
                      const width = max > 0 ? Math.max((value / max) * 100, 1.5) : 0
                      return (
                        <td key={col.key} className="px-4 py-2">
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
        </section>
      )}
    </main>
  )
}
