import type { ArchivedBoard } from './api/archivedBoard'

export interface ReportCard {
  winner: ArchivedBoard['outcomes'][number] | null
  winnerRank: number | null
  top20Hits: number
  top20Picks: number
  top20ByChance: number | null
  cutAcc: number | null
  cutBaseRate: number | null
  n: number
}

// How the PINNED pre-event board compared to the result.
//
// Pure function of an `ArchivedBoard`, never of a live `predictions` fetch:
// the live endpoint recomputes with today's active model, which for an event
// inside that model's training window is an in-sample score — scoring that as
// "the pre-event board" is the defect this replaced. No graded snapshot means
// no report card; there is deliberately no fallback.
//
// Shared by the Leaderboard's completed-event view and the Track Record page,
// which both show this exact card for one week.
export function computeReportCard(archived: ArchivedBoard | undefined): ReportCard | null {
  if (!archived?.available || !archived.graded) return null
  const o = archived.outcomes
  if (o.length === 0) return null
  const winner = o.find((x) => x.final_position === 1) ?? null
  const byWin = [...o].sort((a, b) => b.win_prob - a.win_prob)
  const winnerRank = winner ? byWin.findIndex((x) => x.player_id === winner.player_id) + 1 : null
  // The board's own top-20 picks, and how many of them finished top 20. On a
  // field smaller than 20 every pick is trivially a top-20 finisher, so the
  // denominator follows the field rather than assuming 20.
  const top20Picks = Math.min(20, o.length)
  const boardTop20 = [...o].sort((a, b) => b.top_20_prob - a.top_20_prob).slice(0, top20Picks)
  const top20Hits = boardTop20.filter((x) => x.final_position != null && x.final_position <= 20).length
  // What picking `top20Picks` players at random would have returned: each has
  // a top20Picks/field chance of finishing top 20. Without it, "14 / 20" is a
  // number with nothing to beat.
  const top20ByChance = o.length > 0 ? top20Picks * (top20Picks / o.length) : null

  // Make-cut is graded only where the event actually held a cut. On a no-cut
  // event the backend withholds `made_cut` entirely, so this collapses to
  // null rather than scoring a question nobody asked.
  const cutGraded = archived.event_had_a_cut ? o.filter((x) => x.made_cut != null) : []
  const cutCorrect = cutGraded.filter((x) => (x.make_cut_prob >= 0.5) === x.made_cut).length
  const cutAcc = cutGraded.length ? cutCorrect / cutGraded.length : null
  // The rate you get by calling every player the majority outcome.
  const cutMadeShare = cutGraded.length
    ? cutGraded.filter((x) => x.made_cut).length / cutGraded.length
    : null
  const cutBaseRate = cutMadeShare == null ? null : Math.max(cutMadeShare, 1 - cutMadeShare)

  return {
    winner,
    winnerRank,
    top20Hits,
    top20Picks,
    top20ByChance,
    cutAcc,
    cutBaseRate,
    n: o.length,
  }
}
