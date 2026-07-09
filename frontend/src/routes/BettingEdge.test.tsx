import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BettingEdge } from './BettingEdge'

afterEach(cleanup)

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderEdge(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <BettingEdge />
    </QueryClientProvider>,
  )
}

const TOURNAMENT_FIXTURE = {
  id: 7,
  name: 'The Masters',
  season: 2026,
  start_date: '2026-04-10',
  end_date: '2026-04-13',
  status: 'upcoming',
  course_id: 1,
  purse: 18_000_000,
  field_strength: null,
}

const BOARD_FIXTURE = {
  tournament_id: 7,
  tournament_name: 'The Masters',
  outcome_key: 'win_prob',
  n_positive_ev: 2,
  lines: [
    {
      player_id: 1,
      player_name: 'Rory Birdie',
      model_prob: 0.18,
      implied_prob: 0.14,
      american_odds: 600,
      edge: 0.04,
      ev_per_dollar: 0.12,
      kelly_fraction: 0.03,
    },
    {
      player_id: 2,
      player_name: 'Tiger Chip',
      model_prob: 0.12,
      implied_prob: 0.15,
      american_odds: 500,
      edge: -0.03,
      ev_per_dollar: -0.08,
      kelly_fraction: 0.0,
    },
  ],
}

function mockFetch({
  tournament = TOURNAMENT_FIXTURE as typeof TOURNAMENT_FIXTURE | null,
  board = BOARD_FIXTURE as typeof BOARD_FIXTURE | null,
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
      if (url.includes('betting/edge')) {
        if (board == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => board })
      }
      return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
    }),
  )
}

describe('BettingEdge', () => {
  it('renders the heading immediately', () => {
    mockFetch()
    renderEdge(makeClient())
    expect(screen.getByRole('heading', { name: /Betting Edge/i })).toBeInTheDocument()
  })

  it('shows player name and positive EV badge in the table', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      // getAllByText because the name also appears in the SVG chart
      expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0)
    })
    expect(screen.getByText('+EV')).toBeInTheDocument()
  })

  it('shows formatted American odds', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText('+600')).toBeInTheDocument()
    })
  })

  it('shows the filtered +EV count in the header', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      // Count is computed from the filtered lines with the same +EV predicate as the
      // row badges. With the default ≥10% filter both fixture lines remain (0.18, 0.12),
      // and only Rory (edge +0.04) is +EV → the first positive-coloured span reads "1".
      const positiveSpan = document.querySelector('.text-positive')
      expect(positiveSpan?.textContent).toBe('1')
    })
  })

  it('shows no-tournament message when no active tournament', async () => {
    mockFetch({ tournament: null })
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/No active tournament/i)).toBeInTheDocument()
    })
  })

  it('shows market picker buttons', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Top 5')).toBeInTheDocument()
    })
    expect(screen.getByText('Top 10')).toBeInTheDocument()
    expect(screen.getByText('Make Cut')).toBeInTheDocument()
  })
})
