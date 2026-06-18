import { useState } from 'react'

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

        return (
          <g key={line.player_id}>
            {/* player label */}
            <text
              x={PADDING.left + LABEL_WIDTH - 8}
              y={y + BAR_HEIGHT / 2 + 4}
              textAnchor="end"
              className={`fill-fg text-[11px] ${positive ? 'font-semibold' : ''}`}
            >
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
              fill={positive ? '#4FD1C5' : '#EF4444'}
              opacity={positive ? 0.85 : 0.45}
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
            const positive = line.edge >= 0.005
            return (
              <tr
                key={line.player_id}
                className={`transition-colors hover:bg-surface-2 ${
                  positive ? 'bg-surface' : 'bg-surface opacity-60'
                }`}
              >
                <td className="px-4 py-2 text-right font-mono text-fg-tertiary">{idx + 1}</td>
                <td className="px-4 py-2 font-medium text-fg">
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

function ReliabilityNote({ outcomeKey }: { outcomeKey: OutcomeKey }) {
  const { tier, note } = OUTCOME_RELIABILITY[outcomeKey]
  const style =
    tier === 'medium'
      ? 'border-accent/30 bg-accent/5 text-fg-secondary'
      : 'border-negative/30 bg-negative/5 text-fg-secondary'
  const badge =
    tier === 'medium'
      ? { label: 'Best available market', cls: 'bg-accent/15 text-accent' }
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
      <p className="mt-1.5 leading-relaxed text-fg-tertiary">
        This model improves on a naive base-rate baseline but does not beat a sharp sportsbook.
        Read this board as where the model <em>disagrees</em> with the market — a research signal,
        not guaranteed +EV. Large edges are most often model error, not value.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function BettingEdge() {
  const [outcomeKey, setOutcomeKey] = useState<OutcomeKey>('top_20_prob')

  const { data: currentTournament, isLoading: tournamentLoading } = useCurrentTournament()
  const tournamentId = currentTournament?.id ?? null

  const {
    data: board,
    isLoading: boardLoading,
    isError,
    error,
  } = useBettingEdge(tournamentId, outcomeKey)

  // Compute max absolute edge for chart scale.
  const maxEdge =
    board && board.lines.length > 0
      ? Math.max(...board.lines.map((l) => Math.abs(l.edge)))
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
        {board && (
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-fg-tertiary">
            <span>
              Odds:{' '}
              {board.odds_source === 'datagolf' ? (
                <span className="font-mono text-positive">Live sportsbook consensus</span>
              ) : (
                <span className="font-mono text-accent">Synthetic (model)</span>
              )}
            </span>
            <span>
              Model: <span className="font-mono">Calibrated classifier (golf_v1)</span>
            </span>
            <span>
              Sizing:{' '}
              <span className="font-mono">½-Kelly</span>
            </span>
            <span>
              +EV lines:{' '}
              <span className="font-mono text-positive">{board.n_positive_ev}</span> /{' '}
              {board.lines.length}
            </span>
          </div>
        )}
        <p className="mt-2 text-xs text-fg-tertiary">
          {board?.odds_source === 'datagolf'
            ? 'Odds are a median consensus across sportsbooks (via DataGolf), de-vigged by field normalization. Edge = model probability − fair book-implied probability.'
            : 'No live odds feed configured — odds are synthetic lines from model probabilities with a 10% vig margin. Edge = model probability − book implied probability after vig removal.'}
        </p>
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
          {/* Market selector */}
          <section className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">Market</p>
            <MarketPicker value={outcomeKey} onChange={setOutcomeKey} />
          </section>

          {/* Honest reliability caveat — the model improves on a naive baseline
              but does not beat a sharp sportsbook, so this board is a model-vs-
              market divergence view, not a guaranteed +EV signal. */}
          <ReliabilityNote outcomeKey={outcomeKey} />

          {/* Edge bar chart */}
          <section className="space-y-3">
            <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">
              Edge Distribution (top 20 players)
            </p>
            <div className="overflow-x-auto rounded-lg border bg-surface p-4">
              <EdgeBarChart lines={board.lines} maxEdge={maxEdge} />
            </div>
          </section>

          {/* Full table */}
          <section className="space-y-3">
            <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">
              All Lines — sorted by EV
            </p>
            <LinesTable lines={board.lines} />
          </section>
        </>
      )}
    </main>
  )
}
