/**
 * Benchmark — our model vs. DataGolf's published projections.
 *
 * When DATA_PROVIDER=mock the page renders a callout explaining that a
 * DataGolf API key is needed to populate the DG columns.
 *
 * When DATA_PROVIDER=datagolf the table shows side-by-side win / top-10 /
 * make-cut probabilities for every player in the current field, sorted by
 * the largest absolute divergence so the most interesting disagreements are
 * at the top.
 *
 * Backend: GET /api/v1/analytics/benchmark/{tournament_id}
 */

import { useCurrentTournament } from '../lib/api/tournaments'
import { useBenchmark } from '../lib/api/benchmark'
import type { BenchmarkPlayerRow } from '../lib/api/benchmark'

function formatPct(p: number | null): string {
  if (p == null) return '—'
  return `${(p * 100).toFixed(1)}%`
}

function DiffBadge({ diff }: { diff: number | null }) {
  if (diff == null) return <span className="text-fg-tertiary">—</span>
  const pct = (diff * 100).toFixed(1)
  if (Math.abs(diff) < 0.002) return <span className="text-fg-tertiary">≈0</span>
  return (
    <span className={diff > 0 ? 'text-positive' : 'text-negative'}>
      {diff > 0 ? '+' : ''}{pct}pp
    </span>
  )
}

function DGCallout() {
  return (
    <div className="rounded-lg border border-accent/30 bg-accent/5 px-6 py-5">
      <p className="text-sm font-medium text-fg">DataGolf API not connected</p>
      <p className="mt-1 text-sm text-fg-secondary">
        Set <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-xs">DATA_PROVIDER=datagolf</code> and{' '}
        <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-xs">DATAGOLF_API_KEY=&lt;your-key&gt;</code>{' '}
        to populate the DataGolf columns. Our model's probabilities are live
        regardless.
      </p>
      <p className="mt-2 text-xs text-fg-tertiary">
        Purchase a subscription at{' '}
        <a
          href="https://datagolf.com/api-access"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:underline"
        >
          datagolf.com/api-access
        </a>
      </p>
    </div>
  )
}

function BenchmarkTable({ rows, dgAvailable }: { rows: BenchmarkPlayerRow[]; dgAvailable: boolean }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
            <th className="w-10 px-4 py-3 text-right">#</th>
            <th className="px-4 py-3">Player</th>
            <th className="px-4 py-3 text-right">Our Win</th>
            {dgAvailable && <th className="px-4 py-3 text-right">DG Win</th>}
            {dgAvailable && <th className="px-4 py-3 text-right">Diff</th>}
            <th className="px-4 py-3 text-right">Our Top-10</th>
            {dgAvailable && <th className="px-4 py-3 text-right">DG Top-10</th>}
            <th className="px-4 py-3 text-right">Our Cut</th>
            {dgAvailable && <th className="px-4 py-3 text-right">DG Cut</th>}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((row, idx) => (
            <tr
              key={row.player_id}
              className="bg-surface transition-colors hover:bg-surface-2"
            >
              <td className="px-4 py-2 text-right font-mono text-fg-tertiary">{idx + 1}</td>
              <td className="px-4 py-2 font-medium text-fg">{row.player_name}</td>

              {/* Our win */}
              <td className="px-4 py-2 text-right font-mono tabular-nums text-accent">
                {formatPct(row.our_win_prob)}
              </td>

              {/* DG win + diff */}
              {dgAvailable && (
                <td className="px-4 py-2 text-right font-mono tabular-nums text-fg-secondary">
                  {formatPct(row.dg_win_prob)}
                </td>
              )}
              {dgAvailable && (
                <td className="px-4 py-2 text-right font-mono tabular-nums">
                  <DiffBadge diff={row.win_diff} />
                </td>
              )}

              {/* Our top-10 */}
              <td className="px-4 py-2 text-right font-mono tabular-nums text-fg">
                {formatPct(row.our_top_10_prob)}
              </td>

              {/* DG top-10 */}
              {dgAvailable && (
                <td className="px-4 py-2 text-right font-mono tabular-nums text-fg-secondary">
                  {formatPct(row.dg_top_10_prob)}
                </td>
              )}

              {/* Our cut */}
              <td className="px-4 py-2 text-right font-mono tabular-nums text-fg">
                {formatPct(row.our_make_cut_prob)}
              </td>

              {/* DG cut */}
              {dgAvailable && (
                <td className="px-4 py-2 text-right font-mono tabular-nums text-fg-secondary">
                  {formatPct(row.dg_make_cut_prob)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Benchmark() {
  const { data: currentTournament, isLoading: tLoading } = useCurrentTournament()
  const tournamentId = currentTournament?.id ?? null
  const { data: benchmark, isLoading: bLoading, isError } = useBenchmark(tournamentId)

  const isLoading = tLoading || bLoading

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Model Benchmark</h1>
        <p className="text-sm text-fg-tertiary">
          Our GBDT predictions vs. DataGolf's published ML projections — sorted by
          largest win-probability divergence.
        </p>
      </header>

      {isLoading && <p className="text-fg-secondary">Loading…</p>}

      {isError && (
        <p className="text-negative">
          Could not load benchmark data. Make sure a tournament is active and a
          model has been trained.
        </p>
      )}

      {benchmark && (
        <>
          {/* Tournament + model header */}
          <div className="flex flex-wrap items-baseline gap-4">
            <h2 className="text-base font-semibold">{benchmark.tournament_name}</h2>
            <span className="text-xs text-fg-tertiary">
              model:{' '}
              <span className="font-mono">
                {benchmark.model_name}
                {benchmark.model_version_id
                  ? `@${benchmark.model_version_id.slice(0, 8)}`
                  : ' (fallback)'}
              </span>
            </span>
            {benchmark.dg_available && benchmark.dg_last_updated && (
              <span className="text-xs text-fg-tertiary">
                DG updated: {benchmark.dg_last_updated}
              </span>
            )}
          </div>

          {/* DataGolf not connected callout */}
          {!benchmark.dg_available && <DGCallout />}

          {/* Legend when DG is connected */}
          {benchmark.dg_available && (
            <div className="flex gap-6 text-xs text-fg-tertiary">
              <span>
                <span className="text-positive">+Xpp</span> = we are more bullish than DG
              </span>
              <span>
                <span className="text-negative">−Xpp</span> = DG is more bullish than us
              </span>
            </div>
          )}

          {/* Comparison table */}
          {benchmark.rows.length > 0 ? (
            <BenchmarkTable rows={benchmark.rows} dgAvailable={benchmark.dg_available} />
          ) : (
            <p className="text-fg-secondary">
              No predictions available for this tournament yet.{' '}
              <span className="text-fg-tertiary">
                Run <code className="font-mono">uv run python -m app.cli.train</code> to
                generate them.
              </span>
            </p>
          )}
        </>
      )}

      {/* No active tournament */}
      {!tLoading && !currentTournament && (
        <p className="text-fg-secondary">No active or upcoming tournament found.</p>
      )}
    </main>
  )
}
