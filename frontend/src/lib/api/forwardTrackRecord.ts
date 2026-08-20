import { useQuery } from '@tanstack/react-query'

export interface ForwardMarketSkill {
  market: string
  n: number
  base_rate: number
  brier: number
  brier_skill: number
  // null when the block-bootstrap has too few events to produce a CI (< 3
  // events) — the backend reports the skill point estimate regardless, so the
  // UI must not assume a CI exists.
  ci_lower: number | null
  ci_upper: number | null
}

export interface ForwardTrackRecord {
  available: boolean
  events: number
  players_graded: number
  events_to_meaningful: number
  markets: ForwardMarketSkill[]
  // Serving-regime split of the graded events. Boards served before the
  // 2026-07-29 Path A fix cold-started every player but carry the same
  // `path_a@…` model version id as healthy ones, so a record that mixes them
  // is not measuring one system. Optional: an older backend omits these.
  events_path_a?: number
  events_cold_start_only?: number
  events_regime_unknown?: number
  // Provenance split: events recorded live before play vs reconstructed
  // afterwards by the backfill. `markets` pools both; the per-provenance
  // aggregates below let the UI show them separately, which is the only
  // honest presentation while most of the record is reconstruction.
  // Optional: an older backend omits all six.
  events_captured?: number
  events_backfilled?: number
  players_captured?: number
  players_backfilled?: number
  markets_captured?: ForwardMarketSkill[]
  markets_backfilled?: ForwardMarketSkill[]
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
