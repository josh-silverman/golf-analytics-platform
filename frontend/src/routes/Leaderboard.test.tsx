import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ForwardTrackRecord } from '../lib/api/forwardTrackRecord'
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

// Mirrors the live API shape when there are too few graded events (< 3) to
// bootstrap a CI: the block-bootstrap returns nan, which FastAPI's encoder
// maps to JSON null — win_prob here is representative of a market that's
// still provisional; make_cut_prob is representative of one that's confirmed.
const TRACK_RECORD_PROVISIONAL_FIXTURE = {
  available: true,
  events: 2,
  players_graded: 286,
  events_to_meaningful: 18,
  markets: [
    {
      market: 'win_prob',
      n: 286,
      base_rate: 0.007,
      brier: 0.0069,
      brier_skill: 0.003,
      ci_lower: null,
      ci_upper: null,
    },
    {
      market: 'make_cut_prob',
      n: 286,
      base_rate: 0.486,
      brier: 0.2287,
      brier_skill: 0.0843,
      ci_lower: null,
      ci_upper: null,
    },
  ],
}

const TRACK_RECORD_MIXED_FIXTURE = {
  available: true,
  events: 12,
  players_graded: 1500,
  events_to_meaningful: 0,
  markets: [
    {
      market: 'win_prob',
      n: 1500,
      base_rate: 0.007,
      brier: 0.0069,
      brier_skill: 0.003,
      ci_lower: -0.01,
      ci_upper: 0.02,
    },
    {
      market: 'make_cut_prob',
      n: 1500,
      base_rate: 0.486,
      brier: 0.2287,
      brier_skill: 0.0843,
      ci_lower: 0.031,
      ci_upper: 0.14,
    },
    {
      market: 'top_20_prob',
      n: 1500,
      base_rate: 0.136,
      brier: 0.098,
      brier_skill: 0.061,
      ci_lower: 0.012,
      ci_upper: 0.11,
    },
  ],
}

function mockFetch({
  tournament = TOURNAMENT_FIXTURE as typeof TOURNAMENT_FIXTURE | null,
  predictions = PREDICTIONS_FIXTURE as typeof PREDICTIONS_FIXTURE | null,
  trackRecord = null as ForwardTrackRecord | null,
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
      if (url.includes('track-record/forward')) {
        if (trackRecord == null) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ available: false }) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => trackRecord })
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

  it('renders provisional markets when the CI is null instead of hiding the widget', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_PROVISIONAL_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Forward out-of-sample track record/i)).toBeInTheDocument()
    })
    // Both markets in the fixture have ci_lower: null, so both should render
    // as provisional rather than being filtered out.
    expect(screen.getAllByText('(provisional)')).toHaveLength(2)
    expect(screen.getByText(/~18 more to a stable interval/i)).toBeInTheDocument()
    // Neither market has cleared its CI yet, so the one-line summary must not
    // claim confirmed skill on anything.
    expect(screen.getByText(/Too early to call/i)).toBeInTheDocument()
  })

  it('flags when the graded record mixes serving regimes', async () => {
    // 1 real Path A board + 1 cold-start-only + 1 unrecorded: the aggregate is
    // not measuring a single system and must say so.
    mockFetch({
      trackRecord: {
        ...TRACK_RECORD_MIXED_FIXTURE,
        events_path_a: 1,
        events_cold_start_only: 1,
        events_regime_unknown: 1,
      },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Forward out-of-sample track record/i)).toBeInTheDocument()
    })
    expect(
      screen.getByText(/1 served cold-start only and 1 of unrecorded coverage out of 3/i),
    ).toBeInTheDocument()
  })

  it('omits the regime caveat when every graded board ran Path A', async () => {
    mockFetch({
      trackRecord: {
        ...TRACK_RECORD_MIXED_FIXTURE,
        events_path_a: 12,
        events_cold_start_only: 0,
        events_regime_unknown: 0,
      },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Forward out-of-sample track record/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/serving configuration/i)).not.toBeInTheDocument()
  })

  it('summarizes confirmed vs. still-accumulating markets in plain language', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_MIXED_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Forward out-of-sample track record/i)).toBeInTheDocument()
    })
    // make-cut and top-20 have ci_lower > 0 (confirmed); win does not.
    expect(
      screen.getByText(/Model has beaten the base rate on Make cut and Top 20/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/Win hasn't accumulated enough samples yet to call/i)).toBeInTheDocument()
  })

  it('shows an empty-field message instead of a blank table when outcomes is empty', async () => {
    // Matches what an upcoming event that isn't DataGolf's current week
    // returns live: a valid board with zero outcomes.
    mockFetch({ predictions: { ...PREDICTIONS_FIXTURE, outcomes: [] } })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/No field published for this event yet/i)).toBeInTheDocument()
    })
    expect(screen.queryByText('Rory Birdie')).not.toBeInTheDocument()
    expect(screen.queryByText('How to read this board')).not.toBeInTheDocument()
  })

})
