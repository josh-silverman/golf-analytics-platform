import { useQuery } from '@tanstack/react-query'

export interface ArchivedBoardOutcome {
  player_id: number
  player_name: string
  win_prob: number
  top_5_prob: number
  top_10_prob: number
  top_20_prob: number
  make_cut_prob: number
  final_position: number | null
  // null on an event played without a 36-hole cut, where every player "made" a
  // cut that was never held. The backend withholds it rather than reporting a
  // correct call, matching what the forward record excludes.
  made_cut: boolean | null
}

export interface ArchivedBoard {
  available: boolean
  tournament_id: number
  tournament_name: string | null
  tournament_start_date: string | null
  // "captured" — pinned live before play began. "backfilled" — reconstructed
  // afterwards by a later model over the same pre-event data. null when the
  // ledger holds no snapshot for this event at all.
  source: 'captured' | 'backfilled' | null
  as_of: string | null
  captured_at: string | null
  model_name: string | null
  model_version_id: string | null
  model_trained_through: string | null
  dg_direct_count: number | null
  dg_fetch_status: string | null
  out_of_sample: boolean
  graded: boolean
  event_had_a_cut: boolean
  outcomes: ArchivedBoardOutcome[]
}

async function fetchArchivedBoard(tournamentId: number): Promise<ArchivedBoard> {
  const r = await fetch(`/api/v1/predictions/${tournamentId}/archived`)
  if (!r.ok) throw new Error(`/predictions/${tournamentId}/archived returned ${r.status}`)
  return r.json() as Promise<ArchivedBoard>
}

/**
 * The board that was actually pinned before an event, read from the ledger.
 *
 * Deliberately separate from `usePredictions`: that endpoint recomputes with
 * whatever model is active today, which for an event inside the model's
 * training window is an in-sample score. Only this one can back a claim about
 * what was predicted beforehand.
 *
 * Snapshots are immutable once written, so there is nothing to revalidate.
 */
export function useArchivedBoard(tournamentId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['archived-board', tournamentId],
    queryFn: () => fetchArchivedBoard(tournamentId!),
    enabled: enabled && tournamentId != null,
    staleTime: Infinity,
  })
}
