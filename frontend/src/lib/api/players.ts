import { useQuery } from '@tanstack/react-query'

import type { ListEnvelope, Player, Round, SingleEnvelope } from './types'

// The endpoint caps a page at 200, so walk the cursor to load the whole
// registry (~3.5k players) — otherwise the page shows only the first slice and
// search can't reach everyone. The list is cheap and cached server-side.
const _PAGE_LIMIT = 200

async function fetchPlayers(): Promise<ListEnvelope<Player>> {
  const all: Player[] = []
  let cursor: string | null = null
  let first: ListEnvelope<Player> | null = null

  for (let guard = 0; guard < 200; guard++) {
    const params = new URLSearchParams({ limit: String(_PAGE_LIMIT) })
    if (cursor) params.set('cursor', cursor)
    const r = await fetch(`/api/v1/players?${params.toString()}`)
    if (!r.ok) throw new Error(`/players returned ${r.status}`)
    const page = (await r.json()) as ListEnvelope<Player>
    first ??= page
    all.push(...page.data)
    cursor = page.page.next_cursor
    if (!cursor) break
  }

  const base = first as ListEnvelope<Player>
  return {
    ...base,
    data: all,
    page: { next_cursor: null, has_more: false, total: base.page.total ?? all.length },
  }
}

async function fetchPlayer(id: number): Promise<SingleEnvelope<Player>> {
  const r = await fetch(`/api/v1/players/${id}`)
  if (!r.ok) throw new Error(`/players/${id} returned ${r.status}`)
  return r.json() as Promise<SingleEnvelope<Player>>
}

async function fetchRecentRounds(playerId: number): Promise<ListEnvelope<Round>> {
  const r = await fetch(`/api/v1/players/${playerId}/recent-rounds`)
  if (!r.ok) throw new Error(`/players/${playerId}/recent-rounds returned ${r.status}`)
  return r.json() as Promise<ListEnvelope<Round>>
}

export function usePlayers() {
  // Paginates the whole registry so search reaches every player, not just page 1.
  return useQuery({ queryKey: ['players'], queryFn: fetchPlayers })
}

export function usePlayer(id: number) {
  return useQuery({ queryKey: ['player', id], queryFn: () => fetchPlayer(id) })
}

export function useRecentRounds(playerId: number) {
  return useQuery({
    queryKey: ['recent-rounds', playerId],
    queryFn: () => fetchRecentRounds(playerId),
  })
}
