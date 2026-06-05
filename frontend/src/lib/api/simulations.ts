import { useQuery } from '@tanstack/react-query'

export interface SimulationOutcome {
  player_id: number
  player_name: string
  win_prob: number
  top_5_prob: number
  top_10_prob: number
  top_20_prob: number
  make_cut_prob: number
  expected_score: number
}

export interface TournamentSimulation {
  tournament_id: number
  tournament_name: string
  as_of: string
  n_iterations: number
  score_std: number
  outcomes: SimulationOutcome[]
}

async function fetchSimulation(tournamentId: number): Promise<TournamentSimulation> {
  const r = await fetch(`/api/v1/simulations/${tournamentId}`)
  if (!r.ok) throw new Error(`/simulations/${tournamentId} returned ${r.status}`)
  return r.json() as Promise<TournamentSimulation>
}

export function useSimulation(tournamentId: number | null) {
  return useQuery({
    queryKey: ['simulations', tournamentId],
    queryFn: () => fetchSimulation(tournamentId!),
    enabled: tournamentId != null,
  })
}
