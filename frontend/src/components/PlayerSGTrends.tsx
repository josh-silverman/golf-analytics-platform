/**
 * PlayerSGTrends — the strokes-gained visualisation shared by the full player
 * profile page and the leaderboard's slide-in player drawer.
 *
 * Bespoke SVG sparklines per SG category (OTT, APP, ARG, PUTT, Total), career
 * (window) averages, and a recent-rounds table. No D3 — every coordinate is
 * computed inline. Takes ``rounds`` already ordered chronologically (oldest →
 * newest) so the charts read left → right.
 */

import type { Round } from '../lib/api/types'

// ---------------------------------------------------------------------------
// Sparkline geometry
// ---------------------------------------------------------------------------

const W = 220
const H = 72
const PAD = { top: 8, right: 6, bottom: 8, left: 6 }
const INNER_W = W - PAD.left - PAD.right
const INNER_H = H - PAD.top - PAD.bottom

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

  const toY = (v: number) => PAD.top + INNER_H - ((v - min) / range) * INNER_H
  const toX = (i: number) =>
    values.length === 1
      ? PAD.left + INNER_W / 2
      : PAD.left + (i / (values.length - 1)) * INNER_W

  const points = values.map((v, i) => `${toX(i)},${toY(v)}`).join(' ')

  const zeroY = toY(0)
  const areaPoints = [
    `M ${toX(0)} ${zeroY}`,
    ...values.map((v, i) => `L ${toX(i)} ${toY(v)}`),
    `L ${toX(values.length - 1)} ${zeroY}`,
    'Z',
  ].join(' ')

  const gradId = `sg-grad-${label.replace(/[^a-z]/gi, '')}`

  const latest = values[values.length - 1]
  const trend5 =
    values.length >= 5 ? values.slice(-5).reduce((s, v) => s + v, 0) / 5 : avg

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between px-0.5 text-xs">
        <span className="font-medium uppercase tracking-wider text-fg-tertiary">{label}</span>
        <span className={`font-mono font-semibold ${avg >= 0 ? 'text-positive' : 'text-negative'}`}>
          {avg >= 0 ? '+' : ''}
          {avg.toFixed(2)} avg
        </span>
      </div>

      <div className="overflow-hidden rounded border bg-surface">
        <svg width={W} height={H} aria-label={`${label} strokes gained trend`}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.18" />
              <stop offset="100%" stopColor={color} stopOpacity="0.02" />
            </linearGradient>
          </defs>

          <line
            x1={PAD.left}
            y1={toY(0)}
            x2={W - PAD.right}
            y2={toY(0)}
            stroke="#232B40"
            strokeWidth={1}
            strokeDasharray="3 3"
          />

          <path d={areaPoints} fill={`url(#${gradId})`} />

          <polyline
            points={points}
            fill="none"
            stroke={color}
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {values.length <= 24 &&
            values.map((v, i) => (
              <circle key={i} cx={toX(i)} cy={toY(v)} r={2} fill={color} opacity={0.75} />
            ))}

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

      <p className="px-0.5 text-[10px] text-fg-tertiary">
        Last-5 avg:{' '}
        <span className={`font-mono font-medium ${trend5 >= 0 ? 'text-positive' : 'text-negative'}`}>
          {trend5 >= 0 ? '+' : ''}
          {trend5.toFixed(2)}
        </span>
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SG category config + helpers
// ---------------------------------------------------------------------------

interface SgCategory {
  key: keyof Round
  label: string
  color: string
  description: string
}

const SG_CATEGORIES: SgCategory[] = [
  { key: 'sg_total', label: 'Total', color: '#34A65F', description: 'Strokes gained vs field across all phases' },
  { key: 'sg_ott', label: 'OTT', color: '#3b82f6', description: 'Off the tee' },
  { key: 'sg_app', label: 'APP', color: '#8b5cf6', description: 'Approach' },
  { key: 'sg_arg', label: 'ARG', color: '#f59e0b', description: 'Around the green' },
  { key: 'sg_putt', label: 'PUTT', color: '#10b981', description: 'Putting' },
]

function mean(xs: number[]): number {
  if (xs.length === 0) return 0
  return xs.reduce((s, v) => s + v, 0) / xs.length
}

function formatSgSigned(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(3)}`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

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
                  r.score_to_par < 0 ? 'text-positive' : r.score_to_par > 0 ? 'text-negative' : 'text-fg'
                }`}
              >
                {r.score_to_par === 0 ? 'E' : r.score_to_par > 0 ? `+${r.score_to_par}` : r.score_to_par}
              </td>
              {([r.sg_total, r.sg_ott, r.sg_app, r.sg_arg, r.sg_putt] as number[]).map((v, i) => (
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
// Public component
// ---------------------------------------------------------------------------

export function PlayerSGTrends({ rounds }: { rounds: Round[] }) {
  return (
    <>
      {rounds.length > 0 && (
        <section className="space-y-4">
          <div>
            <h2 className="text-base font-semibold">Strokes Gained Trends</h2>
            <p className="mt-0.5 text-xs text-fg-tertiary">
              Last {rounds.length} rounds, chronological (oldest → newest). Dashed line = zero
              (field average). Dot = each round.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            {SG_CATEGORIES.map(({ key, label, color, description }) => {
              const vals = rounds.map((r) => r[key] as number)
              return (
                <div key={key} title={description}>
                  <Sparkline values={vals} label={label} color={color} avg={mean(vals)} />
                </div>
              )
            })}
          </div>
        </section>
      )}

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
                  <p className="mt-1 font-mono text-lg font-semibold tabular-nums" style={{ color }}>
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

      <section className="space-y-3">
        <h2 className="text-base font-semibold">Recent Rounds</h2>
        {rounds.length === 0 ? (
          <p className="text-fg-secondary">No round data available.</p>
        ) : (
          <RecentRoundsTable rounds={[...rounds].reverse()} />
        )}
      </section>
    </>
  )
}
