import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'

import { TournamentDetail } from './TournamentDetail'

afterEach(cleanup)

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

const TOURNAMENT = {
  id: 1,
  name: 'The Masters',
  season: 2026,
  start_date: '2026-04-10',
  end_date: '2026-04-13',
  status: 'completed' as const,
  course_id: 1,
  purse: 18_000_000,
  field_strength: null,
}

const PREDICTIONS = {
  tournament_id: 1,
  tournament_name: 'The Masters',
  as_of: '2026-04-10',
  model_name: 'golf_v1',
  model_version_id: 'abc123',
  feature_set_hash: 'def456',
  outcomes: [
    {
      player_id: 101,
      player_name: 'Rory McIlroy',
      win_prob: 0.12,
      top_5_prob: 0.35,
      top_10_prob: 0.55,
      top_20_prob: 0.75,
      make_cut_prob: 0.9,
    },
  ],
}

const SIMULATION = {
  tournament_id: 1,
  tournament_name: 'The Masters',
  as_of: '2026-04-10',
  n_iterations: 10000,
  score_std: 2.8,
  outcomes: [
    {
      player_id: 101,
      player_name: 'Rory McIlroy',
      win_prob: 0.11,
      top_5_prob: 0.33,
      top_10_prob: 0.52,
      top_20_prob: 0.72,
      make_cut_prob: 0.88,
      expected_score: -1.2,
    },
  ],
}

const TOURNAMENT_ENVELOPE = {
  data: TOURNAMENT,
  meta: { as_of: '2026-06-05T00:00:00Z', source: 'mock' },
}

function mockFetch({
  tournament = TOURNAMENT_ENVELOPE as typeof TOURNAMENT_ENVELOPE | null,
  predictions = PREDICTIONS as typeof PREDICTIONS | null,
  simulation = SIMULATION as typeof SIMULATION | null,
} = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      if (/\/tournaments\/1$/.test(url)) {
        if (tournament == null)
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        return Promise.resolve({ ok: true, status: 200, json: async () => tournament })
      }
      if (/\/predictions\/1/.test(url)) {
        if (predictions == null)
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        return Promise.resolve({ ok: true, status: 200, json: async () => predictions })
      }
      if (/\/simulations\/1/.test(url)) {
        if (simulation == null)
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        return Promise.resolve({ ok: true, status: 200, json: async () => simulation })
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
    }),
  )
}

function renderDetail(client: QueryClient) {
  return render(
    <MemoryRouter initialEntries={['/tournaments/1']}>
      <QueryClientProvider client={client}>
        <Routes>
          <Route path="/tournaments/:id" element={<TournamentDetail />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('TournamentDetail', () => {
  it('renders the tournament name after load', async () => {
    mockFetch()
    renderDetail(makeClient())
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /The Masters/i })).toBeInTheDocument()
    })
  })

  it('shows season and status', async () => {
    mockFetch()
    renderDetail(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Season 2026/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/completed/i)).toBeInTheDocument()
  })

  it('shows formatted purse', async () => {
    mockFetch()
    renderDetail(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/\$18\.0M/i)).toBeInTheDocument()
    })
  })

  it('renders the top predictions preview', async () => {
    mockFetch()
    renderDetail(makeClient())
    // Player appears in both predictions and simulation tables
    await waitFor(() => {
      expect(screen.getAllByText('Rory McIlroy').length).toBeGreaterThan(0)
    })
    // 12.0% is unique to the predictions win_prob (simulation win is 11.0%)
    expect(screen.getByText('12.0%')).toBeInTheDocument()
  })

  it('renders the simulation preview', async () => {
    mockFetch()
    renderDetail(makeClient())
    await waitFor(() => {
      // Simulation section heading
      expect(screen.getByText(/Monte Carlo Win Probabilities/i)).toBeInTheDocument()
    })
  })

  it('shows not-found for a missing tournament', async () => {
    mockFetch({ tournament: null })
    renderDetail(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Tournament not found/i)).toBeInTheDocument()
    })
  })
})
