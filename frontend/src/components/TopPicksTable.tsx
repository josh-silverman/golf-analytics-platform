/**
 * TopPicksTable — the week's top 10 picks by Top 20 probability, next to what
 * actually happened.
 *
 * HARD RULE: no checkmark/X icons, no green/red pass-fail styling on an
 * individual row. A low probability that didn't happen is the number working
 * correctly, not a miss — every row renders in identical neutral styling
 * regardless of outcome, and the probability + finish sit side by side so the
 * reader draws their own conclusion. Do not add per-row conditional styling
 * keyed to whether the pick "hit".
 */

import type { ArchivedBoard } from '../lib/api/archivedBoard'

const PICK_COUNT = 10

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

function formatFinish(o: ArchivedBoard['outcomes'][number]): string {
  if (o.final_position != null) return `${o.final_position}`
  if (o.made_cut === false) return 'MC'
  return '—'
}

export function TopPicksTable({ board }: { board: ArchivedBoard }) {
  const picks = [...board.outcomes]
    .sort((a, b) => b.top_20_prob - a.top_20_prob)
    .slice(0, Math.min(PICK_COUNT, board.outcomes.length))

  if (picks.length === 0) return null

  return (
    <section className="space-y-3">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">
          Top {picks.length} Picks · Top 20 Probability
        </p>
        <p className="mt-0.5 text-xs text-fg-tertiary">
          The board's highest Top-20 probabilities for the week, next to where each player
          actually finished. A low probability that didn&rsquo;t happen is the number working as
          intended, not a miss.
        </p>
      </div>
      <div className="overflow-hidden rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
              <th className="w-10 px-4 py-3 text-right">#</th>
              <th className="px-4 py-3">Player</th>
              <th className="px-4 py-3 text-right">Top 20 Prob.</th>
              <th className="px-4 py-3 text-right">Finish</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {picks.map((o, idx) => (
              <tr key={o.player_id} className="bg-surface">
                <td className="px-4 py-2 text-right font-mono text-fg-tertiary">{idx + 1}</td>
                <td className="px-4 py-2 font-medium text-fg">{o.player_name}</td>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-fg">
                  {formatPct(o.top_20_prob)}
                </td>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-fg-secondary">
                  {formatFinish(o)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
