import { useQuery } from '@tanstack/react-query'

export type OutcomeKey = 'win_prob' | 'top_5_prob' | 'top_10_prob' | 'top_20_prob' | 'make_cut_prob'

export const OUTCOME_KEYS: OutcomeKey[] = [
  'win_prob',
  'top_5_prob',
  'top_10_prob',
  'top_20_prob',
  'make_cut_prob',
]

export const OUTCOME_LABELS: Record<OutcomeKey, string> = {
  win_prob: 'Win',
  top_5_prob: 'Top 5',
  top_10_prob: 'Top 10',
  top_20_prob: 'Top 20',
  make_cut_prob: 'Make Cut',
}

export interface BettingLine {
  player_id: number
  player_name: string
  model_prob: number
  implied_prob: number
  american_odds: number
  edge: number
  ev_per_dollar: number
  kelly_fraction: number
}

export interface BettingBoard {
  tournament_id: number
  tournament_name: string
  outcome_key: string
  n_positive_ev: number
  lines: BettingLine[]
}

async function fetchBettingEdge(
  tournamentId: number,
  outcomeKey: OutcomeKey,
): Promise<BettingBoard> {
  const url = `/api/v1/betting/edge/${tournamentId}?outcome_key=${outcomeKey}`
  const r = await fetch(url)
  if (!r.ok) throw new Error(`/betting/edge/${tournamentId} returned ${r.status}`)
  return r.json() as Promise<BettingBoard>
}

export function useBettingEdge(tournamentId: number | null, outcomeKey: OutcomeKey = 'win_prob') {
  return useQuery({
    queryKey: ['betting', tournamentId, outcomeKey],
    queryFn: () => fetchBettingEdge(tournamentId!, outcomeKey),
    enabled: tournamentId != null,
  })
}
