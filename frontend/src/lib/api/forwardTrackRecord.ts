import { useQuery } from '@tanstack/react-query'

export interface ForwardMarketSkill {
  market: string
  n: number
  base_rate: number
  brier: number
  brier_skill: number
  ci_lower: number
  ci_upper: number
}

export interface ForwardTrackRecord {
  available: boolean
  events: number
  players_graded: number
  events_to_meaningful: number
  markets: ForwardMarketSkill[]
}

async function fetchForwardTrackRecord(): Promise<ForwardTrackRecord> {
  const r = await fetch('/api/v1/analytics/track-record/forward')
  if (!r.ok) throw new Error(`/analytics/track-record/forward returned ${r.status}`)
  return r.json() as Promise<ForwardTrackRecord>
}

export function useForwardTrackRecord() {
  return useQuery({
    queryKey: ['track-record-forward'],
    queryFn: fetchForwardTrackRecord,
    // Only changes when a completed OOS event is newly graded — cache hard so
    // this cheap, Redis-backed lookup doesn't get re-fetched needlessly.
    staleTime: 6 * 60 * 60 * 1000,
  })
}
