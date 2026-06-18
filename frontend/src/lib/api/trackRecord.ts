import { useQuery } from '@tanstack/react-query'

export interface TrackRecord {
  available: boolean
  events: number
  players_graded: number
  winner_in_top10_rate: number
  mean_winner_rank: number
  avg_top20_hit_rate: number
  make_cut_accuracy: number
  model_name: string | null
  model_version_id: string | null
}

async function fetchTrackRecord(): Promise<TrackRecord> {
  const r = await fetch('/api/v1/analytics/track-record')
  if (!r.ok) throw new Error(`/analytics/track-record returned ${r.status}`)
  return r.json() as Promise<TrackRecord>
}

export function useTrackRecord() {
  return useQuery({
    queryKey: ['track-record'],
    queryFn: fetchTrackRecord,
    // Changes only when events complete; cache hard so the (expensive) board
    // never recomputes on the client side.
    staleTime: 6 * 60 * 60 * 1000,
  })
}
