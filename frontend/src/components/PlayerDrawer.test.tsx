import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BoardSource } from '../lib/boardSource'
import type { PlayerOutcome } from '../lib/api/predictions'
import { PlayerDrawer } from './PlayerDrawer'

afterEach(cleanup)

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
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

const OUTCOME_FIXTURE: PlayerOutcome = {
  player_id: 1,
  player_name: 'Alice Ace',
  win_prob: 0.12,
  top_5_prob: 0.3,
  top_10_prob: 0.45,
  top_20_prob: 0.6,
  make_cut_prob: 0.8,
}

function boardFixture(overrides: Partial<BoardSource> = {}): BoardSource {
  return {
    model_name: 'golf_v2',
    dg_direct_count: null,
    outcomes: [OUTCOME_FIXTURE],
    ...overrides,
  }
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

function renderDrawer(
  client: QueryClient,
  props: Partial<React.ComponentProps<typeof PlayerDrawer>> = {},
) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PlayerDrawer
          playerId={1}
          outcome={OUTCOME_FIXTURE}
          tournamentName="The Masters"
          board={boardFixture()}
          onClose={() => {}}
          {...props}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PlayerDrawer', () => {
  it('renders the player name after load', async () => {
    mockFetch()
    renderDrawer(makeClient())
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Alice Ace' })).toBeInTheDocument()
    })
  })

  // --- source attribution (matches PlayerDetail.test.tsx) ------------------
  // The drawer shows the same five outlook tiles as the full profile page and
  // owes the reader the same honesty about where the numbers came from.

  it('never claims "the active model" produced the outlook', async () => {
    mockFetch()
    renderDrawer(makeClient(), { board: boardFixture({ dg_direct_count: 1 }) })
    await waitFor(() => expect(screen.getByText('Alice Ace')).toBeInTheDocument())
    expect(screen.queryByText(/active model/i)).not.toBeInTheDocument()
  })

  it('attributes a fully DataGolf-direct board correctly', async () => {
    // dg_direct_count equals the outcomes length (1 of 1) → every player direct.
    mockFetch()
    renderDrawer(makeClient(), { board: boardFixture({ dg_direct_count: 1 }) })
    await waitFor(() => {
      expect(screen.getByText(/From DataGolf directly, not the in-house model/i)).toBeInTheDocument()
    })
  })

  it('attributes a cold-started board to the in-house model by name', async () => {
    mockFetch()
    renderDrawer(makeClient(), { board: boardFixture({ dg_direct_count: 0 }) })
    await waitFor(() => {
      expect(
        screen.getByText(/From golf_v2 — DataGolf had no coverage this week/i),
      ).toBeInTheDocument()
    })
  })

  it('does not claim per-player attribution on a mixed board', async () => {
    mockFetch()
    renderDrawer(makeClient(), {
      board: boardFixture({
        dg_direct_count: 1,
        outcomes: [OUTCOME_FIXTURE, { ...OUTCOME_FIXTURE, player_id: 2, player_name: 'Second Player' }],
      }),
    })
    await waitFor(() => {
      // 1 of 2 players direct — honest about not knowing which one Alice is.
      expect(screen.getByText(/DataGolf directly for 1 of 2 players/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/isn't recorded/i)).toBeInTheDocument()
  })

  // --- archived-board path, new to the drawer -------------------------------
  // A completed event's drawer is attributed from the pinned ArchivedBoard
  // snapshot rather than the live TournamentPredictions board.

  it('attributes an archived (completed-event) board with the same label', async () => {
    mockFetch()
    renderDrawer(makeClient(), {
      board: { model_name: 'golf_v2', dg_direct_count: 0, outcomes: [OUTCOME_FIXTURE] },
    })
    await waitFor(() => {
      expect(
        screen.getByText(/From golf_v2 — DataGolf had no coverage this week/i),
      ).toBeInTheDocument()
    })
  })

  it('shows "Source unknown" rather than crashing when no board is passed', async () => {
    mockFetch()
    renderDrawer(makeClient(), { board: null })
    await waitFor(() => expect(screen.getByText('Alice Ace')).toBeInTheDocument())
    expect(screen.getByText(/Source unknown/i)).toBeInTheDocument()
  })

  // At a no-cut event the Make Cut row is the same dead 100.0% the leaderboard
  // hides its column for. The flag comes from the leaderboard so the two
  // surfaces cannot disagree about whether the event has a cut.
  it('omits the Make Cut row at a no-cut event', async () => {
    mockFetch()
    renderDrawer(makeClient(), { eventHasACut: false })
    await waitFor(() => expect(screen.getByText('Alice Ace')).toBeInTheDocument())

    expect(screen.queryByText('Make Cut')).not.toBeInTheDocument()
    // The other four markets are untouched.
    expect(screen.getByText('Top 20')).toBeInTheDocument()
    expect(screen.getByText('Win')).toBeInTheDocument()
  })

  it('shows the Make Cut row by default', async () => {
    mockFetch()
    renderDrawer(makeClient())
    await waitFor(() => expect(screen.getByText('Alice Ace')).toBeInTheDocument())
    expect(screen.getByText('Make Cut')).toBeInTheDocument()
  })
})
