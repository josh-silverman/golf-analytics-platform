import { useQuery } from '@tanstack/react-query'

export interface PlayerOutcome {
  player_id: number
  player_name: string
  win_prob: number
  top_5_prob: number
  top_10_prob: number
  top_20_prob: number
  make_cut_prob: number
  // Actual result once the event is graded; null/absent beforehand.
  final_position?: number | null
  made_cut?: boolean | null
}

export interface TournamentPredictions {
  tournament_id: number
  tournament_name: string
  as_of: string
  model_name: string
  model_version_id: string | null
  feature_set_hash: string
  outcomes: PlayerOutcome[]
  // Players served DataGolf-direct on this board. null when Path A is not in
  // use — the count would be meaningless, since every player goes through the
  // in-house model either way. `model_version_id` alone cannot express this:
  // it reads "path_a@<id>" as soon as Path A is configured, before any
  // DataGolf call happens, so a board that cold-started the whole field
  // carries the same version id as a healthy one (ledger.md §3.2).
  dg_direct_count: number | null
  dg_fetch_status: string | null
}

async function fetchPredictions(tournamentId: number): Promise<TournamentPredictions> {
  const r = await fetch(`/api/v1/predictions/${tournamentId}`)
  if (!r.ok) throw new Error(`/predictions/${tournamentId} returned ${r.status}`)
  return r.json() as Promise<TournamentPredictions>
}

/**
 * The live board: recomputed on request with whatever model is active today.
 *
 * `enabled` exists so a caller can decline it. A completed event is served
 * from the ledger snapshot instead (`useArchivedBoard`), and asking for this
 * one there would both recompute an expensive board nobody displays and
 * produce numbers that are not what was predicted before the event.
 */
export function usePredictions(tournamentId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['predictions', tournamentId],
    queryFn: () => fetchPredictions(tournamentId!),
    enabled: enabled && tournamentId != null,
  })
}
