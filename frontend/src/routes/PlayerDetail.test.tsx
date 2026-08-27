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

const TOURNAMENT_FIXTURE = {
  id: 7,
  name: 'The Masters',
  season: 2026,
  start_date: '2026-04-10',
  end_date: '2026-04-13',
  status: 'in_progress',
  course_id: 1,
  purse: 18_000_000,
  field_strength: null,
}

function predictionsFixture(overrides: Record<string, unknown> = {}) {
  return {
    tournament_id: 7,
    tournament_name: 'The Masters',
    as_of: '2026-04-09',
    model_name: 'golf_v2',
    model_version_id: 'path_a@v2-cold',
    feature_set_hash: 'deadbeef',
    dg_direct_count: null,
    dg_fetch_status: null,
    outcomes: [
      {
        player_id: 1,
        player_name: 'Alice Ace',
        win_prob: 0.12,
        top_5_prob: 0.3,
        top_10_prob: 0.45,
        top_20_prob: 0.6,
        make_cut_prob: 0.8,
      },
    ],
    ...overrides,
  }
}

function mockFetch({
  player = PLAYER_FIXTURE as typeof PLAYER_FIXTURE | null,
  rounds = ROUNDS_FIXTURE as typeof ROUNDS_FIXTURE | null,
  tournament = null as typeof TOURNAMENT_FIXTURE | null,
  predictions = null as ReturnType<typeof predictionsFixture> | null,
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
      if (url.includes('tournaments/current')) {
        if (tournament == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: tournament }) })
      }
      if (url.includes('/predictions/')) {
        if (predictions == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => predictions })
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

  // --- source attribution (audit F3 / H4) ----------------------------------
  // "From the active model" was wrong under Path A: the registry's active
  // model need not be what actually served this board.

  it('never claims "the active model" produced the outlook', async () => {
    mockFetch({
      tournament: TOURNAMENT_FIXTURE,
      predictions: predictionsFixture({ dg_direct_count: 1, dg_fetch_status: 'ok' }),
    })
    renderDetail(1, makeClient())
    await waitFor(() => expect(screen.getByText(/Current Event Outlook/i)).toBeInTheDocument())
    expect(screen.queryByText(/active model/i)).not.toBeInTheDocument()
  })

  it('attributes a fully DataGolf-direct board correctly', async () => {
    // dg_direct_count equals the outcomes length (1 of 1) → every player direct.
    mockFetch({
      tournament: TOURNAMENT_FIXTURE,
      predictions: predictionsFixture({ dg_direct_count: 1, dg_fetch_status: 'ok' }),
    })
    renderDetail(1, makeClient())
    await waitFor(() => {
      expect(screen.getByText(/From DataGolf directly, not the in-house model/i)).toBeInTheDocument()
    })
  })

  it('attributes a cold-started board to the in-house model by name', async () => {
    mockFetch({
      tournament: TOURNAMENT_FIXTURE,
      predictions: predictionsFixture({ dg_direct_count: 0, dg_fetch_status: 'no_coverage' }),
    })
    renderDetail(1, makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(/From golf_v2 — DataGolf had no coverage this week/i),
      ).toBeInTheDocument()
    })
  })

  it('does not claim per-player attribution on a mixed board', async () => {
    mockFetch({
      tournament: TOURNAMENT_FIXTURE,
      predictions: predictionsFixture({
        dg_direct_count: 1,
        dg_fetch_status: 'ok',
        outcomes: [
          predictionsFixture().outcomes[0],
          { ...predictionsFixture().outcomes[0], player_id: 2, player_name: 'Second Player' },
        ],
      }),
    })
    renderDetail(1, makeClient())
    await waitFor(() => {
      // 1 of 2 players direct — honest about not knowing which one Alice is.
      expect(screen.getByText(/DataGolf directly for 1 of 2 players/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/isn't recorded/i)).toBeInTheDocument()
  })
})
