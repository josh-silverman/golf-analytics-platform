import { useQuery } from '@tanstack/react-query'

export interface ArchivedBoardSummary {
  tournament_id: number
  tournament_name: string
  tournament_start_date: string
  source: 'captured' | 'backfilled'
  out_of_sample: boolean
  // Whether a settlement is pinned for this tournament. Stricter than the
  // single-board endpoint's `graded` (which also accepts a live field read
  // when no settlement exists yet) — see the backend docstring on
  // `ArchivedBoardSummaryPayload.graded`. Backs the Track Record page's
  // default-event selection (most recent graded event).
  graded: boolean
}

async function fetchArchivedBoardList(): Promise<ArchivedBoardSummary[]> {
  const r = await fetch('/api/v1/predictions/archived')
  if (!r.ok) throw new Error(`/predictions/archived returned ${r.status}`)
  return r.json() as Promise<ArchivedBoardSummary[]>
}

/**
 * Every tournament with a pinned board, newest first — metadata only, no
 * probabilities. Backs the Track Record page's event picker.
 *
 * Distinct from `useArchivedBoard`, which fetches one week's full board:
 * this is the list of which weeks exist at all, driven by the ledger rather
 * than the DataGolf schedule, so it can reach back to the earliest pinned
 * board instead of stopping at whatever `/tournaments` still lists.
 */
export function useArchivedBoardList() {
  return useQuery({
    queryKey: ['archived-board-list'],
    queryFn: fetchArchivedBoardList,
    staleTime: 5 * 60 * 1000,
  })
}
