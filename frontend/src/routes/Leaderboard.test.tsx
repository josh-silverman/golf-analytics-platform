import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Leaderboard } from './Leaderboard'

afterEach(cleanup)

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderLeaderboard(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Leaderboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const TOURNAMENT_FIXTURE = {
  id: 3,
  name: 'The Open',
  season: 2026,
  start_date: '2026-07-10',
  end_date: '2026-07-13',
  status: 'upcoming',
  course_id: 1,
  purse: 15_000_000,
  field_strength: null,
}

const PREDICTIONS_FIXTURE = {
  tournament_id: 3,
  tournament_name: 'The Open',
  as_of: '2026-07-09',
  model_name: 'golf_v1',
  model_version_id: 'v-abc123',
  feature_set_hash: 'deadbeef1234',
  outcomes: [
    {
      player_id: 1,
      player_name: 'Rory Birdie',
      win_prob: 0.12,
      top_5_prob: 0.35,
      top_10_prob: 0.55,
      top_20_prob: 0.72,
      make_cut_prob: 0.88,
    },
    {
      player_id: 2,
      player_name: 'Tiger Chip',
      win_prob: 0.07,
      top_5_prob: 0.22,
      top_10_prob: 0.40,
      top_20_prob: 0.58,
      make_cut_prob: 0.80,
    },
  ],
}

function mockFetch({
  tournament = TOURNAMENT_FIXTURE as typeof TOURNAMENT_FIXTURE | null,
  predictions = PREDICTIONS_FIXTURE as typeof PREDICTIONS_FIXTURE | null,
} = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      if (url.includes('tournaments/current')) {
        if (tournament == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: tournament }) })
      }
      if (url.includes('predictions')) {
        if (predictions == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => predictions })
      }
      return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
    }),
  )
}

describe('Leaderboard', () => {
  it('renders the heading immediately', () => {
    mockFetch()
    renderLeaderboard(makeClient())
    expect(screen.getByRole('heading', { name: /Leaderboard/i })).toBeInTheDocument()
  })

  it('shows player rows when predictions load', async () => {
    mockFetch()
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Rory Birdie')).toBeInTheDocument()
    })
    expect(screen.getByText('Tiger Chip')).toBeInTheDocument()
  })

  it('formats win probability as percentage', async () => {
    mockFetch()
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText('12.0%')).toBeInTheDocument()
    })
  })

  it('shows tournament name after load', async () => {
    mockFetch()
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/The Open/)).toBeInTheDocument()
    })
  })

  it('shows no-tournament message when none active', async () => {
    mockFetch({ tournament: null })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/No active tournament/i)).toBeInTheDocument()
    })
  })

  it('shows error message when predictions fail', async () => {
    mockFetch({ predictions: null })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Error:/i)).toBeInTheDocument()
    })
  })

})
