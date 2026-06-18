/**
 * PlayerDetail — per-player SG trend analysis.
 *
 * The centrepiece is a bespoke SVG sparkline for each strokes-gained
 * category (OTT, APP, ARG, PUTT, Total).  Data flows from the existing
 * /players/{id}/recent-rounds endpoint (up to 50 rounds, most-recent
 * first) and is reversed before plotting so the x-axis reads
 * chronologically left → right.
 *
 * No D3 is imported; every path coordinate is computed inline so the
 * chart stays a pure TSX component with no extra dependencies.
 */

import { Link, useParams } from 'react-router'

import { usePlayer, useRecentRounds } from '../lib/api/players'
import { usePredictions } from '../lib/api/predictions'
import { useCurrentTournament } from '../lib/api/tournaments'
import type { Round } from '../lib/api/types'

// Current-event model outlook. Same honest emphasis as the leaderboard: Win is
// de-emphasised (the model doesn't sharply pick one winner), Top 20 highlighted
// as the most reliable market.
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

// ---------------------------------------------------------------------------
// Sparkline geometry constants
// ---------------------------------------------------------------------------

const W = 220
const H = 72
const PAD = { top: 8, right: 6, bottom: 8, left: 6 }
const INNER_W = W - PAD.left - PAD.right
const INNER_H = H - PAD.top - PAD.bottom

// ---------------------------------------------------------------------------
// Sparkline component
// ---------------------------------------------------------------------------

interface SparklineProps {
  values: number[]
  label: string
  color: string
  avg: number
}

function Sparkline({ values, label, color, avg }: SparklineProps) {
  if (values.length === 0) return null

  const min = Math.min(...values, -0.05)
  const max = Math.max(...values, 0.05)
  const range = max - min || 1

  // Map value → SVG y (inverted: higher value = lower y = higher on screen)
  const toY = (v: number) => PAD.top + INNER_H - ((v - min) / range) * INNER_H
  const toX = (i: number) =>
    values.length === 1
      ? PAD.left + INNER_W / 2
      : PAD.left + (i / (values.length - 1)) * INNER_W

  // Polyline points
  const points = values.map((v, i) => `${toX(i)},${toY(v)}`).join(' ')

  // Filled area path: line down the values, then close at the zero baseline
  const zeroY = toY(0)
  const areaPoints = [
    `M ${toX(0)} ${zeroY}`,
    ...values.map((v, i) => `L ${toX(i)} ${toY(v)}`),
    `L ${toX(values.length - 1)} ${zeroY}`,
    'Z',
  ].join(' ')

  // Unique gradient id per label so multiple sparklines don't collide
  const gradId = `sg-grad-${label.replace(/[^a-z]/gi, '')}`

  // Latest value for the annotation
  const latest = values[values.length - 1]
  const trend5 =
    values.length >= 5
      ? values.slice(-5).reduce((s, v) => s + v, 0) / 5
      : avg

  return (
    <div className="flex flex-col gap-1">
      {/* Header row: label + avg */}
      <div className="flex items-center justify-between px-0.5 text-xs">
        <span className="font-medium uppercase tracking-wider text-fg-tertiary">{label}</span>
        <span
          className={`font-mono font-semibold ${
            avg >= 0 ? 'text-positive' : 'text-negative'
          }`}
        >
          {avg >= 0 ? '+' : ''}
          {avg.toFixed(2)} avg
        </span>
      </div>

      {/* SVG chart */}
      <div className="overflow-hidden rounded border bg-surface">
        <svg width={W} height={H} aria-label={`${label} strokes gained trend`}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.18" />
              <stop offset="100%" stopColor={color} stopOpacity="0.02" />
            </linearGradient>
          </defs>

          {/* Zero reference line */}
          <line
            x1={PAD.left}
            y1={toY(0)}
            x2={W - PAD.right}
            y2={toY(0)}
            stroke="var(--color-border)"
            strokeWidth={1}
            strokeDasharray="3 3"
          />

          {/* Filled area */}
          <path d={areaPoints} fill={`url(#${gradId})`} />

          {/* Main line */}
          <polyline
            points={points}
            fill="none"
            stroke={color}
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {/* Dots — only when there are few enough points to be readable */}
          {values.length <= 24 &&
            values.map((v, i) => (
              <circle
                key={i}
                cx={toX(i)}
                cy={toY(v)}
                r={2}
                fill={color}
                opacity={0.75}
              />
            ))}

          {/* Latest value annotation */}
          <text
            x={W - PAD.right - 2}
            y={Math.max(PAD.top + 10, Math.min(H - PAD.bottom - 2, toY(latest) - 4))}
            textAnchor="end"
            fontSize={9}
            fontFamily="monospace"
            fill={color}
            opacity={0.9}
          >
            {latest >= 0 ? '+' : ''}
            {latest.toFixed(2)}
          </text>
        </svg>
      </div>

      {/* 5-round rolling average */}
      <p className="px-0.5 text-[10px] text-fg-tertiary">
        Last-5 avg:{' '}
        <span
          className={`font-mono font-medium ${
            trend5 >= 0 ? 'text-positive' : 'text-negative'
          }`}
        >
          {trend5 >= 0 ? '+' : ''}
          {trend5.toFixed(2)}
        </span>
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SG category config
// ---------------------------------------------------------------------------

interface SgCategory {
  key: keyof Round
  label: string
  color: string
  description: string
}

const SG_CATEGORIES: SgCategory[] = [
  {
    key: 'sg_total',
    label: 'Total',
    color: 'var(--color-accent)',
    description: 'Strokes gained vs field across all phases',
  },
  {
    key: 'sg_ott',
    label: 'OTT',
    color: '#3b82f6',
    description: 'Off the tee',
  },
  {
    key: 'sg_app',
    label: 'APP',
    color: '#8b5cf6',
    description: 'Approach',
  },
  {
    key: 'sg_arg',
    label: 'ARG',
    color: '#f59e0b',
    description: 'Around the green',
  },
  {
    key: 'sg_putt',
    label: 'PUTT',
    color: '#10b981',
    description: 'Putting',
  },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mean(xs: number[]): number {
  if (xs.length === 0) return 0
  return xs.reduce((s, v) => s + v, 0) / xs.length
}

function formatSgSigned(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(3)}`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

// ---------------------------------------------------------------------------
// Recent Rounds Table
// ---------------------------------------------------------------------------

function RecentRoundsTable({ rounds }: { rounds: Round[] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
            <th className="px-4 py-3">Date</th>
            <th className="px-4 py-3 text-center">Rnd</th>
            <th className="px-4 py-3 text-right">Score</th>
            <th className="px-4 py-3 text-right">SG:Tot</th>
            <th className="px-4 py-3 text-right">OTT</th>
            <th className="px-4 py-3 text-right">APP</th>
            <th className="px-4 py-3 text-right">ARG</th>
            <th className="px-4 py-3 text-right">PUTT</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rounds.map((r) => (
            <tr key={r.id} className="bg-surface transition-colors hover:bg-surface-2">
              <td className="px-4 py-2 text-fg-secondary">{formatDate(r.tee_time)}</td>
              <td className="px-4 py-2 text-center font-mono text-fg-tertiary">{r.round_number}</td>
              <td
                className={`px-4 py-2 text-right font-mono tabular-nums font-medium ${
                  r.score_to_par < 0
                    ? 'text-positive'
                    : r.score_to_par > 0
                      ? 'text-negative'
                      : 'text-fg'
                }`}
              >
                {r.score_to_par === 0 ? 'E' : r.score_to_par > 0 ? `+${r.score_to_par}` : r.score_to_par}
              </td>
              {(
                [
                  r.sg_total,
                  r.sg_ott,
                  r.sg_app,
                  r.sg_arg,
                  r.sg_putt,
                ] as number[]
              ).map((v, i) => (
                <td
                  key={i}
                  className={`px-4 py-2 text-right font-mono tabular-nums text-xs ${
                    v >= 0 ? 'text-positive' : 'text-negative'
                  }`}
                >
                  {formatSgSigned(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function PlayerDetail() {
  const { id } = useParams<{ id: string }>()
  const playerId = Number(id)

  const { data: playerEnv, isLoading: playerLoading, isError: playerError } = usePlayer(playerId)
  const { data: roundsEnv, isLoading: roundsLoading } = useRecentRounds(playerId)

  // Current-event model probabilities for this player (cheap — the board is
  // cached server-side). Empty when there's no active event or the player isn't
  // in its field.
  const { data: currentTournament } = useCurrentTournament()
  const { data: predictions } = usePredictions(currentTournament?.id ?? null)
  const outlook = predictions?.outcomes.find((o) => o.player_id === playerId) ?? null

  const player = playerEnv?.data
  // API returns most-recent first; reverse so chart reads oldest → newest
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
      {/* Back link */}
      <Link to="/players" className="text-sm text-fg-secondary hover:text-fg">
        ← Players
      </Link>

      {/* Player header */}
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
          <span>
            {rounds.length} rounds loaded
          </span>
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
            <p className="text-sm text-fg-tertiary">
              Not in the field for {currentTournament.name}.
            </p>
          )}
        </section>
      )}

      {/* SG Trend Charts */}
      {rounds.length > 0 && (
        <section className="space-y-4">
          <div>
            <h2 className="text-base font-semibold">Strokes Gained Trends</h2>
            <p className="mt-0.5 text-xs text-fg-tertiary">
              Last {rounds.length} rounds, chronological (oldest → newest).
              Dashed line = zero (field average). Dot = each round.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            {SG_CATEGORIES.map(({ key, label, color, description }) => {
              const vals = rounds.map((r) => r[key] as number)
              return (
                <div key={key} title={description}>
                  <Sparkline
                    values={vals}
                    label={label}
                    color={color}
                    avg={mean(vals)}
                  />
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* SG category summary cards */}
      {rounds.length > 0 && (
        <section>
          <h2 className="mb-3 text-base font-semibold">Career Averages ({rounds.length} rounds)</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {SG_CATEGORIES.map(({ key, label, color }) => {
              const vals = rounds.map((r) => r[key] as number)
              const avg = mean(vals)
              const last5Avg = mean(vals.slice(-5))
              return (
                <div key={key} className="rounded-lg border bg-surface p-3">
                  <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">
                    SG:{label}
                  </p>
                  <p
                    className="mt-1 text-lg font-mono font-semibold tabular-nums"
                    style={{ color }}
                  >
                    {avg >= 0 ? '+' : ''}
                    {avg.toFixed(3)}
                  </p>
                  <p className="mt-0.5 text-[10px] text-fg-tertiary">
                    L5: {last5Avg >= 0 ? '+' : ''}
                    {last5Avg.toFixed(3)}
                  </p>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* Recent rounds table */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold">Recent Rounds</h2>
        {rounds.length === 0 ? (
          <p className="text-fg-secondary">No round data available.</p>
        ) : (
          <RecentRoundsTable rounds={[...rounds].reverse()} />
        )}
      </section>
    </main>
  )
}
