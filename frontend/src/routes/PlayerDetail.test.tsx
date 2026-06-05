import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PlayerDetail } from './PlayerDetail'

afterEach(cleanup)

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderDetail(playerId: number, client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/players/${playerId}`]}>
        <Routes>
          <Route path="/players/:id" element={<PlayerDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const PLAYER_FIXTURE = {
  id: 1,
  dg_id: 1001,
  full_name: 'Alice Ace',
  country: 'USA',
  dob: null,
  turned_pro: 2015,
}

function makeRound(id: number, overrides: Partial<Record<string, number | string | null>> = {}) {
  return {
    id,
    entry_id: 100,
    round_number: 1,
    score: 68,
    score_to_par: -3,
    tee_time: '2026-04-10T08:00:00Z',
    sg_ott: 0.8,
    sg_app: 0.5,
    sg_arg: 0.2,
    sg_putt: 0.4,
    sg_t2g: 1.5,
    sg_total: 1.9,
    driving_distance_avg: null,
    fairways_hit: null,
    gir: null,
    putts: null,
    ...overrides,
  }
}

const ROUNDS_FIXTURE = {
  data: [makeRound(1), makeRound(2), makeRound(3)],
  page: { next_cursor: null, has_more: false, total: 3 },
  meta: { as_of: '2026-04-10T00:00:00Z', source: 'mock' },
}

function mockFetch({
  player = PLAYER_FIXTURE as typeof PLAYER_FIXTURE | null,
  rounds = ROUNDS_FIXTURE as typeof ROUNDS_FIXTURE | null,
} = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      if (url.includes('recent-rounds')) {
        if (rounds == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => rounds })
      }
      // single player fetch
      if (url.match(/\/players\/\d+$/)) {
        if (player == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ data: player, meta: { as_of: '2026-04-10T00:00:00Z', source: 'mock' } }),
        })
      }
      return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
    }),
  )
}

describe('PlayerDetail', () => {
  it('renders the player name after load', async () => {
    mockFetch()
    renderDetail(1, makeClient())
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Alice Ace' })).toBeInTheDocument()
    })
  })

  it('shows country and turned-pro year', async () => {
    mockFetch()
    renderDetail(1, makeClient())
    await waitFor(() => {
      expect(screen.getByText('USA')).toBeInTheDocument()
    })
    expect(screen.getByText('2015')).toBeInTheDocument()
  })

  it('renders SG category labels', async () => {
    mockFetch()
    renderDetail(1, makeClient())
    await waitFor(() => {
      // Labels appear in sparkline + summary cards; use getAllBy
      expect(screen.getAllByText('OTT').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('APP').length).toBeGreaterThan(0)
    expect(screen.getAllByText('ARG').length).toBeGreaterThan(0)
    expect(screen.getAllByText('PUTT').length).toBeGreaterThan(0)
  })

  it('shows not-found message for missing player', async () => {
    mockFetch({ player: null, rounds: null })
    renderDetail(999, makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Player not found/i)).toBeInTheDocument()
    })
  })

  it('shows round count in the header', async () => {
    mockFetch()
    renderDetail(1, makeClient())
    await waitFor(() => {
      expect(screen.getByText(/3 rounds loaded/)).toBeInTheDocument()
    })
  })

  it('renders sparkline SVGs for each SG category', async () => {
    mockFetch()
    renderDetail(1, makeClient())
    await waitFor(() => {
      const svgs = document.querySelectorAll('svg[aria-label*="strokes gained"]')
      expect(svgs.length).toBe(5)
    })
  })
})
