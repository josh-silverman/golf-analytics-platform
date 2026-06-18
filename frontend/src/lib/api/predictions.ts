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
}

async function fetchPredictions(tournamentId: number): Promise<TournamentPredictions> {
  const r = await fetch(`/api/v1/predictions/${tournamentId}`)
  if (!r.ok) throw new Error(`/predictions/${tournamentId} returned ${r.status}`)
  return r.json() as Promise<TournamentPredictions>
}

export function usePredictions(tournamentId: number | null) {
  return useQuery({
    queryKey: ['predictions', tournamentId],
    queryFn: () => fetchPredictions(tournamentId!),
    enabled: tournamentId != null,
  })
}
