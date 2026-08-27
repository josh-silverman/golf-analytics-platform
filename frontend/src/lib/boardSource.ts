/**
 * Where a served board's probabilities actually came from.
 *
 * Shared by the full player profile (`routes/PlayerDetail.tsx`) and the
 * leaderboard's slide-in drawer (`components/PlayerDrawer.tsx`), which show
 * the same five outlook tiles and so owe the reader the same attribution.
 */

// The minimal shape this needs. Both `TournamentPredictions` (the live board)
// and `ArchivedBoard` (the pinned ledger snapshot a completed event serves)
// satisfy it, which is what lets one label describe either. Only `.length` is
// read off `outcomes`, so the element type is deliberately not constrained.
export interface BoardSource {
  model_name: string | null
  dg_direct_count: number | null
  outcomes: unknown[]
}

// "From the active model" was wrong under Path A: most of the field is served
// DataGolf's own probabilities, not the in-house model, and the registry's
// active model can differ from what a specific board is actually stamped
// with (ledger.md §3.1). There is no per-player source recorded, only a
// board-level count, so this states the board's composition rather than
// claiming to know this one player's source.
export function sourceLabel(board: BoardSource | undefined | null): string {
  // `model_name` is null only on an archived board with no snapshot, where
  // there is no board on screen to describe — the same "nothing to report"
  // case the missing-board guard already covers.
  if (!board || board.model_name == null) return 'Source unknown'
  const total = board.outcomes.length
  const direct = board.dg_direct_count
  if (direct == null) {
    return `From ${board.model_name}`
  }
  if (direct === 0) {
    return `From ${board.model_name} — DataGolf had no coverage this week, so the whole field was cold-started`
  }
  if (direct === total) {
    return 'From DataGolf directly, not the in-house model'
  }
  return `Board mixes sources: DataGolf directly for ${direct} of ${total} players, ${board.model_name} for the rest — which one covers this player isn't recorded`
}
