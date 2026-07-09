import { useMemo, useState } from 'react'

import {
  OUTCOME_KEYS,
  OUTCOME_LABELS,
  OUTCOME_RELIABILITY,
  type BettingLine,
  type OutcomeKey,
  useBettingEdge,
} from '../lib/api/betting'
import { useCurrentTournament } from '../lib/api/tournaments'

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatPct(p: number, decimals = 1): string {
  return `${(p * 100).toFixed(decimals)}%`
}

function formatEdge(edge: number): string {
  const pct = (edge * 100).toFixed(1)
  return edge >= 0 ? `+${pct}%` : `${pct}%`
}

function formatAmerican(odds: number): string {
  return odds >= 0 ? `+${odds}` : `${odds}`
}

function formatEv(ev: number): string {
  const cents = (ev * 100).toFixed(1)
  return ev >= 0 ? `+${cents}¢` : `${cents}¢`
}

function formatKelly(k: number): string {
  if (k === 0) return '—'
  return `${(k * 100).toFixed(1)}%`
}

// ---------------------------------------------------------------------------
// Signal classification helpers
// ---------------------------------------------------------------------------

// A line reads as +EV when the model probability exceeds the fair book-implied
// probability by a small buffer. Used for the row badge and the header count so
// the two always agree.
function isPositive(line: BettingLine): boolean {
  return line.edge >= 0.005
}

// The most actionable divergences: the model probability is high enough that the
// edge is likely informative (≥20%) AND the edge is large enough to matter (≥+3%).
// A small edge on a 4% longshot is mostly noise; these are not.
function isHighConfidence(line: BettingLine): boolean {
  return line.model_prob >= 0.2 && line.edge >= 0.03
}

// Minimum model-probability filter options for the table. Default is ≥10% so the
// view immediately surfaces meaningful divergences instead of longshot noise,
// while "All" restores the full list.
const PROB_THRESHOLDS: { label: string; value: number }[] = [
  { label: 'All', value: 0 },
  { label: '≥10%', value: 0.1 },
  { label: '≥20%', value: 0.2 },
  { label: '≥30%', value: 0.3 },
]

// ---------------------------------------------------------------------------
// Edge bar chart (custom SVG visualisation)
//
// Renders a horizontal diverging bar chart: positive edge extends right
// (accent colour), negative edge extends left (muted red). The zero line
// sits in the centre so viewers can read both direction and magnitude at a
// glance — a standard viz used by sports-betting analytics teams.
// ---------------------------------------------------------------------------

const BAR_HEIGHT = 16
const BAR_GAP = 6
const CHART_ROW_HEIGHT = BAR_HEIGHT + BAR_GAP
const LABEL_WIDTH = 160
const AXIS_WIDTH = 300 // total half-width (left + right) of chart area
const PADDING = { top: 24, right: 16, bottom: 28, left: 8 }

function EdgeBarChart({ lines, maxEdge }: { lines: BettingLine[]; maxEdge: number }) {
  // Show at most 20 players so the chart stays readable.
  const visible = lines.slice(0, 20)
  const scale = maxEdge > 0 ? (AXIS_WIDTH / 2) / maxEdge : 1

  const svgWidth = LABEL_WIDTH + AXIS_WIDTH + PADDING.left + PADDING.right
  const svgHeight = PADDING.top + visible.length * CHART_ROW_HEIGHT + PADDING.bottom

  const zeroX = PADDING.left + LABEL_WIDTH + AXIS_WIDTH / 2

  return (
    <svg
      width={svgWidth}
      height={svgHeight}
      aria-label="Edge bar chart"
      className="select-none overflow-visible font-mono text-xs"
    >
      {/* zero axis */}
      <line
        x1={zeroX}
        y1={PADDING.top - 8}
        x2={zeroX}
        y2={PADDING.top + visible.length * CHART_ROW_HEIGHT}
        stroke="#232B40"
        strokeWidth={1}
      />

      {/* axis labels */}
      <text
        x={zeroX - AXIS_WIDTH / 2}
        y={PADDING.top - 10}
        textAnchor="middle"
        className="fill-fg-tertiary text-[10px]"
      >
        −{formatEdge(maxEdge).replace('+', '')}
      </text>
      <text x={zeroX} y={PADDING.top - 10} textAnchor="middle" className="fill-fg-tertiary text-[10px]">
        0%
      </text>
      <text
        x={zeroX + AXIS_WIDTH / 2}
        y={PADDING.top - 10}
        textAnchor="middle"
        className="fill-fg-tertiary text-[10px]"
      >
        {formatEdge(maxEdge)}
      </text>

      {visible.map((line, i) => {
        const y = PADDING.top + i * CHART_ROW_HEIGHT
        const barWidth = Math.abs(line.edge) * scale
        const positive = line.edge >= 0.005
        const highConf = isHighConfidence(line)

        // High-confidence lines (≥20% model prob AND ≥+3% edge) render brighter and
        // fully opaque with a thin outline so they stand out from noisier +EV bars.
        const fill = highConf ? '#4ADE80' : positive ? '#34A65F' : '#EF4444'
        const opacity = highConf ? 1 : positive ? 0.85 : 0.45

        return (
          <g key={line.player_id}>
            {/* player label */}
            <text
              x={PADDING.left + LABEL_WIDTH - 8}
              y={y + BAR_HEIGHT / 2 + 4}
              textAnchor="end"
              className={`fill-fg text-[11px] ${positive ? 'font-semibold' : ''}`}
            >
              {highConf ? '★ ' : ''}
              {line.player_name.length > 22
                ? line.player_name.slice(0, 21) + '…'
                : line.player_name}
            </text>

            {/* bar */}
            <rect
              x={positive ? zeroX : zeroX - barWidth}
              y={y}
              width={Math.max(barWidth, 2)}
              height={BAR_HEIGHT}
              rx={2}
              fill={fill}
              opacity={opacity}
              stroke={highConf ? '#4ADE80' : 'none'}
              strokeWidth={highConf ? 1 : 0}
            />

            {/* edge value label */}
            <text
              x={positive ? zeroX + barWidth + 4 : zeroX - barWidth - 4}
              y={y + BAR_HEIGHT / 2 + 4}
              textAnchor={positive ? 'start' : 'end'}
              className={`fill-fg-secondary text-[10px]`}
            >
              {formatEdge(line.edge)}
            </text>
          </g>
        )
      })}

      {/* bottom axis ticks */}
      {[-1, -0.5, 0, 0.5, 1].map((frac) => {
        const x = zeroX + frac * (AXIS_WIDTH / 2)
        return (
          <line
            key={frac}
            x1={x}
            y1={PADDING.top + visible.length * CHART_ROW_HEIGHT}
            x2={x}
            y2={PADDING.top + visible.length * CHART_ROW_HEIGHT + 4}
            stroke="#232B40"
            strokeWidth={1}
          />
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Market selector
// ---------------------------------------------------------------------------

function MarketPicker({
  value,
  onChange,
}: {
  value: OutcomeKey
  onChange: (k: OutcomeKey) => void
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {OUTCOME_KEYS.map((key) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
            key === value
              ? 'bg-accent text-white'
              : 'border bg-surface text-fg-secondary hover:text-fg'
          }`}
        >
          {OUTCOME_LABELS[key]}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Minimum model-probability filter
// ---------------------------------------------------------------------------

function ProbabilityFilter({
  value,
  onChange,
}: {
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {PROB_THRESHOLDS.map((t) => (
        <button
          key={t.value}
          onClick={() => onChange(t.value)}
          className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
            t.value === value
              ? 'bg-accent text-white'
              : 'border bg-surface text-fg-secondary hover:text-fg'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Lines table
// ---------------------------------------------------------------------------

function LinesTable({ lines }: { lines: BettingLine[] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
            <th className="w-10 px-4 py-3 text-right">#</th>
            <th className="px-4 py-3">Player</th>
            <th className="px-4 py-3 text-right">Model</th>
            <th className="px-4 py-3 text-right">Implied</th>
            <th className="px-4 py-3 text-right">Odds</th>
            <th className="px-4 py-3 text-right">Edge</th>
            <th className="px-4 py-3 text-right">EV / $1</th>
            <th className="px-4 py-3 text-right">½-Kelly</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {lines.map((line, idx) => {
            const positive = isPositive(line)
            const highConf = isHighConfidence(line)
            return (
              <tr
                key={line.player_id}
                className={`transition-colors hover:bg-surface-2 ${
                  highConf
                    ? 'border-l-2 border-accent bg-accent/5'
                    : positive
                      ? 'bg-surface'
                      : 'bg-surface opacity-60'
                }`}
              >
                <td className="px-4 py-2 text-right font-mono text-fg-tertiary">{idx + 1}</td>
                <td className="px-4 py-2 font-medium text-fg">
                  {highConf && (
                    <span
                      className="mr-1 text-accent"
                      title="High-confidence signal: ≥20% model probability and ≥+3% edge"
                    >
                      ★
                    </span>
                  )}
                  {line.player_name}
                  {positive && (
                    <span className="ml-2 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                      +EV
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-fg">
                  {formatPct(line.model_prob)}
                </td>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-fg-secondary">
                  {formatPct(line.implied_prob)}
                </td>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-fg">
                  {formatAmerican(line.american_odds)}
                </td>
                <td
                  className={`px-4 py-2 text-right font-mono tabular-nums font-semibold ${
                    positive ? 'text-positive' : 'text-negative'
                  }`}
                >
                  {formatEdge(line.edge)}
                </td>
                <td
                  className={`px-4 py-2 text-right font-mono tabular-nums ${
                    positive ? 'text-positive' : 'text-fg-tertiary'
                  }`}
                >
                  {formatEv(line.ev_per_dollar)}
                </td>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-accent">
                  {formatKelly(line.kelly_fraction)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Reliability note — honest, per-market framing of how much to trust the edge
// ---------------------------------------------------------------------------

function ReliabilityNote({
  outcomeKey,
  oddsSource,
}: {
  outcomeKey: OutcomeKey
  oddsSource: string
}) {
  const base = OUTCOME_RELIABILITY[outcomeKey]

  // The hardcoded map assumes make-cut has no live book market (tier 'synthetic').
  // The live board can override that: when odds_source is 'datagolf' the lines are a
  // real sportsbook consensus, so we promote the market out of the synthetic tier and
  // describe the edge as a genuine model-vs-market comparison instead of a vig artifact.
  // Symmetrically, a real-odds market that comes back synthetic is demoted. The badge
  // therefore reflects the live odds source, not the stale assumption.
  const liveOdds = oddsSource === 'datagolf'
  const overrodeSynthetic = base.tier === 'synthetic' && liveOdds
  const tier = overrodeSynthetic ? 'medium' : base.tier
  const note = overrodeSynthetic
    ? 'Best-calibrated market (+0.25 Brier skill), now priced against a live sportsbook consensus — divergences are a genuine model-vs-market comparison. Still a research signal, not guaranteed value.'
    : base.note

  const style =
    tier === 'medium'
      ? 'border-accent/30 bg-accent/5 text-fg-secondary'
      : 'border-negative/30 bg-negative/5 text-fg-secondary'
  const badge =
    tier === 'medium'
      ? {
          label: liveOdds ? 'Live odds · best market' : 'Best available market',
          cls: 'bg-accent/15 text-accent',
        }
      : tier === 'synthetic'
        ? { label: 'Synthetic odds', cls: 'bg-negative/15 text-negative' }
        : { label: 'Low confidence', cls: 'bg-negative/15 text-negative' }

  return (
    <div className={`rounded-lg border px-4 py-3 text-xs ${style}`}>
      <div className="flex items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${badge.cls}`}>
          {badge.label}
        </span>
        <span className="font-medium text-fg">{OUTCOME_LABELS[outcomeKey]} market</span>
      </div>
      <p className="mt-1.5 leading-relaxed">{note}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function BettingEdge() {
  const [outcomeKey, setOutcomeKey] = useState<OutcomeKey>('make_cut_prob')
  // Default to ≥10% so the table opens on meaningful divergences, not longshot noise.
  const [minProb, setMinProb] = useState<number>(0.1)

  const { data: currentTournament, isLoading: tournamentLoading } = useCurrentTournament()
  const tournamentId = currentTournament?.id ?? null

  const {
    data: board,
    isLoading: boardLoading,
    isError,
    error,
  } = useBettingEdge(tournamentId, outcomeKey)

  // Apply the minimum-probability filter, then sort by edge descending so the
  // largest positive divergences sit on top and negatives fall to the bottom.
  const filteredLines = useMemo(() => {
    if (!board) return []
    return board.lines
      .filter((l) => l.model_prob >= minProb)
      .sort((a, b) => b.edge - a.edge)
  }, [board, minProb])

  // Header count reflects the filtered set, using the same +EV predicate as the
  // row badges so the number always matches the badges the user can see.
  const filteredPositive = filteredLines.filter(isPositive).length

  // Compute max absolute edge for chart scale (from the filtered set).
  const maxEdge =
    filteredLines.length > 0
      ? Math.max(...filteredLines.map((l) => Math.abs(l.edge)))
      : 0.1

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Betting Edge</h1>
        {currentTournament && (
          <p className="mt-1 text-sm text-fg-secondary">
            {currentTournament.name} ·{' '}
            {new Date(currentTournament.start_date).toLocaleDateString()}
          </p>
        )}
        <p className="mt-2 text-xs leading-relaxed text-fg-tertiary">
          Where the model diverges from the market — model probabilities vs. book-implied odds
          for the current field (research, not a guaranteed +EV signal). Make Cut and Top 20 carry
          validated skill; Win is intentionally coarse.
        </p>
        {board && (
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-fg-tertiary">
            <span>
              +EV lines:{' '}
              <span className="font-mono text-positive">{filteredPositive}</span> /{' '}
              {filteredLines.length}
              {minProb > 0 && (
                <span className="text-fg-tertiary"> (≥{Math.round(minProb * 100)}% filter)</span>
              )}
            </span>
          </div>
        )}
      </header>

      {(tournamentLoading || boardLoading) && (
        <p className="text-fg-secondary">Loading lines…</p>
      )}

      {!tournamentLoading && currentTournament == null && (
        <p className="text-fg-secondary">No active tournament found.</p>
      )}

      {isError && (
        <p className="text-negative">
          Error: {error instanceof Error ? error.message : 'Unknown failure'}
        </p>
      )}

      {board && (
        <>
          {/* Market selector — ordered by validated skill (Make Cut → … → Win) */}
          <section className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">Market</p>
            <MarketPicker value={outcomeKey} onChange={setOutcomeKey} />
          </section>

          {/* Honest reliability caveat — the model improves on a naive baseline
              but does not beat a sharp sportsbook, so this board is a model-vs-
              market divergence view, not a guaranteed +EV signal. */}
          <ReliabilityNote outcomeKey={outcomeKey} oddsSource={board.odds_source} />

          {/* Minimum model-probability filter — drops longshot noise from the view. */}
          <section className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">
              Min. model probability
            </p>
            <ProbabilityFilter value={minProb} onChange={setMinProb} />
            <p className="text-[11px] italic text-fg-tertiary">
              Tip: filter to ≥20% model probability to focus on the most reliable divergences. A
              small edge on a low-probability longshot is mostly noise. ★ marks the most actionable
              signals (≥20% model probability and ≥+3% edge).
            </p>
          </section>

          {filteredLines.length === 0 ? (
            <p className="rounded-lg border border-negative/30 bg-negative/5 px-4 py-6 text-center text-sm text-fg-secondary">
              No players meet the ≥{Math.round(minProb * 100)}% model-probability threshold for this
              market. Lower the filter to see more lines.
            </p>
          ) : (
            <>
              {/* Edge bar chart */}
              <section className="space-y-3">
                <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">
                  Edge Distribution (top 20 by edge)
                </p>
                <div className="overflow-x-auto rounded-lg border bg-surface p-4">
                  <EdgeBarChart lines={filteredLines} maxEdge={maxEdge} />
                </div>
              </section>

              {/* Full table */}
              <section className="space-y-3">
                <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">
                  All Lines — sorted by edge (high → low)
                </p>
                <LinesTable lines={filteredLines} />
              </section>
            </>
          )}
        </>
      )}
    </main>
  )
}
