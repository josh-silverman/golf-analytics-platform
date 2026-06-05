import { useQuery } from '@tanstack/react-query'

import type { ListEnvelope, Player, Round, SingleEnvelope } from './types'

async function fetchPlayers(limit = 100): Promise<ListEnvelope<Player>> {
  const r = await fetch(`/api/v1/players?limit=${limit}`)
  if (!r.ok) throw new Error(`/players returned ${r.status}`)
  return r.json() as Promise<ListEnvelope<Player>>
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
  return useQuery({ queryKey: ['players'], queryFn: () => fetchPlayers() })
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
