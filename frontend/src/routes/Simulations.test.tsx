import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Simulations } from './Simulations'

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderSimulations(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <Simulations />
    </QueryClientProvider>,
  )
}

const TOURNAMENT_FIXTURE = {
  id: 5,
  name: 'The Open',
  season: 2026,
  start_date: '2026-07-10',
  end_date: '2026-07-13',
  status: 'upcoming',
  course_id: 1,
  purse: 15_000_000,
  field_strength: null,
}

const SIM_FIXTURE = {
  tournament_id: 5,
  tournament_name: 'The Open',
  as_of: '2026-07-09',
  n_iterations: 10000,
  score_std: 3.3,
  outcomes: [
    {
      player_id: 1,
      player_name: 'Rory Birdie',
      win_prob: 0.085,
      top_5_prob: 0.28,
      top_10_prob: 0.45,
      top_20_prob: 0.65,
      make_cut_prob: 0.88,
      expected_score: -2.1,
    },
  ],
}

function mockFetch({
  tournament = TOURNAMENT_FIXTURE as typeof TOURNAMENT_FIXTURE | null,
  simulation = SIM_FIXTURE as typeof SIM_FIXTURE | null,
} = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      if ((url as string).includes('tournaments/current')) {
        if (tournament == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: tournament }) })
      }
      if ((url as string).includes('simulations')) {
        if (simulation == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => simulation })
      }
      return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
    }),
  )
}

describe('Simulations', () => {
  it('renders the heading immediately', () => {
    mockFetch()
    renderSimulations(makeClient())
    expect(screen.getByRole('heading', { name: /Simulation/i })).toBeInTheDocument()
  })

  it('shows player rows when simulation data loads', async () => {
    mockFetch()
    renderSimulations(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Rory Birdie')).toBeInTheDocument()
    })
    expect(screen.getByText('8.5%')).toBeInTheDocument() // win_prob formatted
  })

  it('shows no-tournament message when no active tournament', async () => {
    mockFetch({ tournament: null })
    renderSimulations(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/No active tournament/i)).toBeInTheDocument()
    })
  })

  it('labels the method as Monte Carlo', async () => {
    mockFetch()
    renderSimulations(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Monte Carlo')).toBeInTheDocument()
    })
  })
})
