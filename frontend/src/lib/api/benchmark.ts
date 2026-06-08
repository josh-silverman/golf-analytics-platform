import { useQuery } from '@tanstack/react-query'

export interface BenchmarkPlayerRow {
  player_id: number
  player_name: string
  our_win_prob: number
  our_top_10_prob: number
  our_make_cut_prob: number
  dg_win_prob: number | null
  dg_top_10_prob: number | null
  dg_make_cut_prob: number | null
  win_diff: number | null
}

export interface BenchmarkPayload {
  tournament_id: number
  tournament_name: string
  model_name: string
  model_version_id: string | null
  dg_available: boolean
  dg_last_updated: string | null
  rows: BenchmarkPlayerRow[]
}

async function fetchBenchmark(tournamentId: number): Promise<BenchmarkPayload> {
  const r = await fetch(`/api/v1/analytics/benchmark/${tournamentId}`)
  if (!r.ok) throw new Error(`/analytics/benchmark/${tournamentId} returned ${r.status}`)
  return r.json() as Promise<BenchmarkPayload>
}

export function useBenchmark(tournamentId: number | null) {
  return useQuery({
    queryKey: ['benchmark', tournamentId],
    queryFn: () => fetchBenchmark(tournamentId!),
    enabled: tournamentId != null,
  })
}
