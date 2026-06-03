import { useQuery } from '@tanstack/react-query'

export interface HealthzResponse {
  status: string
}

async function fetchHealthz(): Promise<HealthzResponse> {
  const response = await fetch('/api/v1/healthz')
  if (!response.ok) {
    throw new Error(`/healthz returned ${response.status}`)
  }
  return response.json() as Promise<HealthzResponse>
}

export function useHealthz() {
  return useQuery({
    queryKey: ['healthz'],
    queryFn: fetchHealthz,
  })
}
