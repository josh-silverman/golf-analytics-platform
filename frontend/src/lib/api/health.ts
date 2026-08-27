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

export interface Status {
  model_name: string
  // The REGISTRY's active model version — not what a served board is stamped
  // with. Boards carry "path_a@<id>" as soon as Path A is configured, which
  // can be a different, older id than this one (ledger.md §3.1). Do not
  // present this as "the model that made this board".
  model_version_id: string | null
  training_data_through: string | null
  serving_strategy: string
  data_provider: string
  provider_reachable: 'ok' | 'unreachable'
  last_board_build_at: string | null
}

async function fetchStatus(): Promise<Status> {
  const r = await fetch('/api/v1/status')
  if (!r.ok) throw new Error(`/status returned ${r.status}`)
  return r.json() as Promise<Status>
}

/**
 * Registry/serving snapshot — which model is active, what it was trained
 * through, and whether the configured data provider currently answers.
 *
 * Explicitly NOT what a specific board was served with: `model_version_id`
 * here can differ from the id a board's own payload carries. Pair with a
 * board's own `dg_direct_count` to know what actually served that board.
 */
export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: fetchStatus,
    staleTime: 5 * 60 * 1000,
  })
}
