import { useQuery } from '@tanstack/react-query'

export type OutcomeKey = 'win_prob' | 'top_5_prob' | 'top_10_prob' | 'top_20_prob' | 'make_cut_prob'

// Ordered by VALIDATED MODEL SKILL, not by market name. Make-cut (+0.246) and
// top-20 (+0.141) carry genuine backtest skill and lead; top-10 follows; top-5
// and win are intentionally coarse (skill ≈ 0) and come last. This order drives
// the Betting Edge market picker so the trustworthy markets are surfaced first.
export const OUTCOME_KEYS: OutcomeKey[] = [
  'make_cut_prob',
  'top_20_prob',
  'top_10_prob',
  'top_5_prob',
  'win_prob',
]

export const OUTCOME_LABELS: Record<OutcomeKey, string> = {
  win_prob: 'Win',
  top_5_prob: 'Top 5',
  top_10_prob: 'Top 10',
  top_20_prob: 'Top 20',
  make_cut_prob: 'Make Cut',
}

// Per-market reliability, grounded in the rolling-origin backtest (skill vs a
// base-rate baseline) and live odds availability. This is deliberately honest:
// the model improves on a naive baseline but does NOT beat a sharp sportsbook,
// so large edges are most likely model error, not exploitable value. We surface
// that here so the board reads as model-vs-market *divergence* (research), not a
// "+EV" money printer.
//   - win/top_5: model calibration is coarse (few positive examples → isotonic
//     collapses to a near-flat plateau); divergences are mostly noise.
//   - top_10/top_20: best model resolution + real book odds, but still
//     mis-rates individual players vs the book.
//   - make_cut: best-calibrated market, but NO live book odds (synthetic lines),
//     so its "edge" is a vig artifact, not a real comparison.
export const OUTCOME_RELIABILITY: Record<
  OutcomeKey,
  { tier: 'low' | 'medium' | 'synthetic'; note: string }
> = {
  win_prob: {
    tier: 'low',
    note: 'Win probabilities are coarse (model can’t separate this market); edges are likely noise.',
  },
  top_5_prob: {
    tier: 'low',
    note: 'Thin model resolution on this market; treat edges as directional only.',
  },
  top_10_prob: {
    tier: 'medium',
    note: 'Model’s strongest real-odds markets, but it still mis-rates individual players vs the book.',
  },
  top_20_prob: {
    tier: 'medium',
    note: 'Model’s strongest real-odds markets, but it still mis-rates individual players vs the book.',
  },
  make_cut_prob: {
    tier: 'synthetic',
    note: 'No live sportsbook make-cut market — odds are synthetic, so the edge is a vig artifact, not real.',
  },
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
  odds_source: string
}

export interface BettingBoard {
  tournament_id: number
  tournament_name: string
  outcome_key: string
  n_positive_ev: number
  odds_source: string
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

export function useBettingEdge(tournamentId: number | null, outcomeKey: OutcomeKey = 'make_cut_prob') {
  return useQuery({
    queryKey: ['betting', tournamentId, outcomeKey],
    queryFn: () => fetchBettingEdge(tournamentId!, outcomeKey),
    enabled: tournamentId != null,
  })
}
