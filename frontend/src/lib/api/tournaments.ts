import { useQuery } from '@tanstack/react-query'

import type { ListEnvelope, Tournament } from './types'

async function fetchTournaments(season?: number): Promise<ListEnvelope<Tournament>> {
  const params = new URLSearchParams({ limit: '200' })
  if (season != null) params.set('season', String(season))
  const r = await fetch(`/api/v1/tournaments?${params.toString()}`)
  if (!r.ok) throw new Error(`/tournaments returned ${r.status}`)
  return r.json() as Promise<ListEnvelope<Tournament>>
}

async function fetchCurrentTournament(): Promise<Tournament | null> {
  const r = await fetch('/api/v1/tournaments/current')
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`/tournaments/current returned ${r.status}`)
  const body = (await r.json()) as { data: Tournament }
  return body.data
}

export function useTournaments(season?: number) {
  return useQuery({
    queryKey: ['tournaments', season],
    queryFn: () => fetchTournaments(season),
  })
}

export function useCurrentTournament() {
  return useQuery({ queryKey: ['tournaments', 'current'], queryFn: fetchCurrentTournament })
}
