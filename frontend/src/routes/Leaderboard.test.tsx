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

// Filler players, to lift a fixture field over SLEEPER_MIN_FIELD (100) so the
// Sleeper tile is not suppressed by field size while a test is checking the
// pick rule itself. Every filler sits above the 5% Win ceiling so it can never
// become the pick, and carries a make_cut_prob below 1.0 so the field never
// reads as a no-cut event.
type FixtureOutcome = {
  player_id: number
  player_name: string
  win_prob: number
  top_5_prob: number
  top_10_prob: number
  top_20_prob: number
  make_cut_prob: number
}

function padField(outcomes: FixtureOutcome[], to: number): FixtureOutcome[] {
  const filler = Array.from({ length: Math.max(0, to - outcomes.length) }, (_, i) => ({
    player_id: 1000 + i,
    player_name: `Filler ${i}`,
    win_prob: 0.06,
    top_5_prob: 0.1,
    top_10_prob: 0.12,
    top_20_prob: 0.15,
    make_cut_prob: 0.5,
  }))
  return [...outcomes, ...filler]
}

// A field seed containing exactly one valid sleeper (Longshot Lou), used to
// check that field size alone decides whether the tile appears. Padded to the
// size each test needs.
const SLEEPER_SEED = [
  { player_id: 1, player_name: 'Favorite Fred', win_prob: 0.2, top_5_prob: 0.5, top_10_prob: 0.7, top_20_prob: 0.9, make_cut_prob: 0.95 },
  { player_id: 3, player_name: 'Longshot Lou', win_prob: 0.01, top_5_prob: 0.15, top_10_prob: 0.25, top_20_prob: 0.4, make_cut_prob: 0.85 },
]

const PREDICTIONS_FIXTURE = {
  tournament_id: 3,
  tournament_name: 'The Open',
  as_of: '2026-07-09',
  model_name: 'golf_v1',
  model_version_id: 'v-abc123',
  feature_set_hash: 'deadbeef1234',
  dg_direct_count: null as number | null,
  dg_fetch_status: null as string | null,
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

// Mirrors the live record as of 2026-08-20: 2 live captures + 7 backfilled
// reconstructions, with per-provenance market aggregates. The captured pool
// has too few events for CIs (null); the backfilled pool clears on make-cut.
const TRACK_RECORD_SPLIT_FIXTURE: ForwardTrackRecord = {
  available: true,
  events: 9,
  players_graded: 1239,
  events_to_meaningful: 11,
  events_path_a: 7,
  events_cold_start_only: 0,
  events_regime_unknown: 2,
  events_captured: 2,
  events_backfilled: 7,
  players_captured: 303,
  players_backfilled: 936,
  markets: [
    {
      market: 'make_cut_prob',
      n: 1171,
      base_rate: 0.51,
      brier: 0.2235,
      brier_skill: 0.106,
      ci_lower: 0.083,
      ci_upper: 0.126,
    },
  ],
  markets_captured: [
    {
      market: 'make_cut_prob',
      n: 300,
      base_rate: 0.503,
      brier: 0.2237,
      brier_skill: 0.109,
      ci_lower: null,
      ci_upper: null,
    },
  ],
  markets_backfilled: [
    {
      market: 'make_cut_prob',
      n: 871,
      base_rate: 0.512,
      brier: 0.2234,
      brier_skill: 0.105,
      ci_lower: 0.08,
      ci_upper: 0.13,
    },
  ],
}

const COMPLETED_TOURNAMENT_FIXTURE = { ...TOURNAMENT_FIXTURE, status: 'completed' }

// The board as it was pinned before play. Deliberately carries DIFFERENT
// probabilities from PREDICTIONS_FIXTURE, so a report card built from the live
// recomputation instead of the ledger is visible as a wrong number rather than
// passing by coincidence.
const ARCHIVED_BOARD_FIXTURE = {
  available: true,
  tournament_id: 3,
  tournament_name: 'The Open',
  tournament_start_date: '2026-07-10',
  source: 'captured' as const,
  as_of: '2026-07-09',
  captured_at: '2026-07-09T21:00:00+00:00',
  model_name: 'golf_v1',
  model_version_id: 'path_a@v2-cold',
  model_trained_through: '2026-06-24',
  dg_direct_count: 2,
  dg_fetch_status: 'ok',
  out_of_sample: true,
  graded: true,
  event_had_a_cut: true,
  outcomes: [
    {
      player_id: 2,
      player_name: 'Tiger Chip',
      win_prob: 0.31,
      top_5_prob: 0.52,
      top_10_prob: 0.66,
      top_20_prob: 0.81,
      make_cut_prob: 0.92,
      final_position: 1,
      made_cut: true,
    },
    {
      player_id: 1,
      player_name: 'Rory Birdie',
      win_prob: 0.09,
      top_5_prob: 0.24,
      top_10_prob: 0.41,
      top_20_prob: 0.60,
      make_cut_prob: 0.71,
      final_position: 14,
      made_cut: true,
    },
    {
      player_id: 3,
      player_name: 'Jordan Fade',
      win_prob: 0.02,
      top_5_prob: 0.08,
      top_10_prob: 0.15,
      top_20_prob: 0.30,
      make_cut_prob: 0.35,
      final_position: null,
      made_cut: false,
    },
  ],
}

const STATUS_FIXTURE = {
  model_name: 'golf_v3',
  model_version_id: 'v3_20260620',
  training_data_through: '2026-06-20',
  serving_strategy: 'path_a',
  data_provider: 'datagolf',
  provider_reachable: 'ok' as const,
  last_board_build_at: '2026-08-20T02:25:00+00:00',
}

function mockFetch({
  tournament = TOURNAMENT_FIXTURE as typeof TOURNAMENT_FIXTURE | null,
  predictions = PREDICTIONS_FIXTURE as typeof PREDICTIONS_FIXTURE | null,
  trackRecord = null as ForwardTrackRecord | null,
  archived = ARCHIVED_BOARD_FIXTURE as Record<string, unknown> | null,
  status = null as typeof STATUS_FIXTURE | null,
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
      if (url.includes('/api/v1/status')) {
        if (status == null) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => status })
      }
      // Must precede the generic `predictions` branch — the archived board
      // lives under /predictions/{id}/archived and has a different shape.
      if (url.includes('/archived')) {
        if (archived == null) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => archived })
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

  it('states the record is too early rather than claiming a lead', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_PROVISIONAL_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(/Too early to say whether the board beats the field-average baseline/i),
      ).toBeInTheDocument()
    })
    // The one-liner still names the graded count.
    expect(screen.getByText(/2 events graded/i)).toBeInTheDocument()
    // And links out to the full per-week record.
    expect(screen.getByRole('link', { name: /See the full record/i })).toHaveAttribute(
      'href',
      '/track-record',
    )
  })

  it('names the live and reconstructed split in the one-line summary', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_SPLIT_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(/9 events graded, 2 predicted live and 7 reconstructed/i),
      ).toBeInTheDocument()
    })
  })

  it('summarizes which markets clear the baseline in plain language', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_MIXED_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      // make-cut and top-20 have ci_lower > 0; win does not.
      expect(
        screen.getByText(/Ahead of the field-average baseline on Make cut and Top 20/i),
      ).toBeInTheDocument()
    })
  })

  it('does not claim an unqualified "most reliable" market in the Win tooltip', async () => {
    mockFetch()
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getAllByText(/Rory Birdie/).length).toBeGreaterThan(0))
    const winHeader = screen.getByRole('button', { name: /Sort by Win/i })
    expect(winHeader.getAttribute('title')).not.toMatch(/most reliable signal/i)
    expect(winHeader.getAttribute('title')).toMatch(/intentionally de-emphasised/i)
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
  })

  // --- summary tiles (Field / Sleeper / Coverage) ---------------------------

  const SLEEPER_FIELD_FIXTURE = {
    ...PREDICTIONS_FIXTURE,
    outcomes: [
      // Favorite: real win equity, must never be picked as the sleeper even
      // though it has the largest Top-20-minus-Win gap in the field.
      { player_id: 1, player_name: 'Favorite Fred', win_prob: 0.2, top_5_prob: 0.5, top_10_prob: 0.7, top_20_prob: 0.9, make_cut_prob: 0.95 },
      // Eligible (win_prob < 5%), lower Top 20 — should lose to Longshot Lou.
      { player_id: 2, player_name: 'Dark Horse', win_prob: 0.03, top_5_prob: 0.1, top_10_prob: 0.2, top_20_prob: 0.3, make_cut_prob: 0.8 },
      // Eligible, highest Top 20 among eligible players — the expected pick.
      { player_id: 3, player_name: 'Longshot Lou', win_prob: 0.01, top_5_prob: 0.15, top_10_prob: 0.25, top_20_prob: 0.4, make_cut_prob: 0.85 },
    ],
  }
  // Padded past the small-field floor, so this exercises the pick rule rather
  // than the suppression rule.
  const SLEEPER_FIELD_FIXTURE_FULL = {
    ...SLEEPER_FIELD_FIXTURE,
    outcomes: padField(SLEEPER_FIELD_FIXTURE.outcomes, 100),
  }

  it('picks the highest Top 20 probability among players under the Win ceiling', async () => {
    mockFetch({ predictions: SLEEPER_FIELD_FIXTURE_FULL })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getAllByText(/Favorite Fred/).length).toBeGreaterThan(0))
    // Favorite Fred has the largest gap (90 - 20 = 70 pts) but 20% win equity,
    // so the ceiling excludes it. Between the two eligible players, Longshot
    // Lou has the higher Top 20 (40% vs 30%) and wins.
    expect(screen.getByText(/Longshot Lou · 40% Top 20 · 1% Win/i)).toBeInTheDocument()
    // Dark Horse is in the field (and its table row), just not the sleeper pick.
    expect(screen.queryByText(/Dark Horse · \d+% Top 20/i)).not.toBeInTheDocument()
  })

  it('omits the sleeper tile when nobody clears the Win ceiling', async () => {
    // Padded past the small-field floor so the omission can only be the Win
    // ceiling: every player here, filler included, has win_prob >= 5%.
    mockFetch({
      predictions: {
        ...PREDICTIONS_FIXTURE,
        outcomes: padField(PREDICTIONS_FIXTURE.outcomes, 100),
      },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getAllByText(/Rory Birdie/).length).toBeGreaterThan(0))
    expect(screen.queryByText(/Sleeper/i)).not.toBeInTheDocument()
    // Field tile still renders.
    expect(screen.getByText('100 players')).toBeInTheDocument()
  })

  // --- report card reads the pinned board, not a recomputation (audit F4) ---

  it('scores a captured event against the pinned pre-event board', async () => {
    mockFetch({ tournament: COMPLETED_TOURNAMENT_FIXTURE })
    renderLeaderboard(makeClient())

    await waitFor(() => {
      expect(screen.getByText(/Predicted live/i)).toBeInTheDocument()
    })
    expect(
      screen.getByText(/scored against the board recorded before play began/i),
    ).toBeInTheDocument()

    // Tiger won and was the archived board's top win% pick, so #1 by win%.
    // On the LIVE fixture Rory has the higher win prob (0.12 vs 0.07), so a
    // report card built from the recomputation would rank the winner #2.
    expect(screen.getByText(/Tiger Chip · board #1 by win%/i)).toBeInTheDocument()
    expect(screen.queryByText(/board #2 by win%/i)).not.toBeInTheDocument()
  })

  it('attaches a baseline to every report-card figure', async () => {
    mockFetch({ tournament: COMPLETED_TOURNAMENT_FIXTURE })
    renderLeaderboard(makeClient())

    await waitFor(() => expect(screen.getByText(/Predicted live/i)).toBeInTheDocument())
    expect(screen.getByText(/by chance/i)).toBeInTheDocument()
    // Two of three made the cut → always-guessing "made" scores 66.7%.
    expect(screen.getByText(/66\.7% always-guess/i)).toBeInTheDocument()
  })

  it('scales the top-20 tile to the field rather than assuming 20 players', async () => {
    // A 156-player field where the board's top 20 by top_20_prob contains 6
    // genuine top-20 finishers. Picking 20 at random returns 20 × 20/156 ≈ 2.6,
    // so the tile has to state 2.6 for "6" to mean anything.
    const outcomes = Array.from({ length: 156 }, (_, i) => ({
      player_id: i + 1,
      player_name: `P${i + 1}`,
      win_prob: 0.3 - i * 0.001,
      top_5_prob: 0.5 - i * 0.002,
      top_10_prob: 0.6 - i * 0.002,
      top_20_prob: 0.9 - i * 0.004,
      make_cut_prob: 0.95 - i * 0.004,
      final_position: i < 6 ? i + 1 : i < 40 ? 21 + i : null,
      made_cut: i < 80,
    }))
    mockFetch({
      tournament: COMPLETED_TOURNAMENT_FIXTURE,
      archived: { ...ARCHIVED_BOARD_FIXTURE, outcomes },
    })
    renderLeaderboard(makeClient())

    await waitFor(() => expect(screen.getByText(/Predicted live/i)).toBeInTheDocument())
    expect(screen.getByText(/6 \/ 20 · 2\.6 by chance/i)).toBeInTheDocument()
  })

  it('labels a backfilled board as reconstructed', async () => {
    mockFetch({
      tournament: COMPLETED_TOURNAMENT_FIXTURE,
      archived: { ...ARCHIVED_BOARD_FIXTURE, source: 'backfilled' },
    })
    renderLeaderboard(makeClient())

    await waitFor(() => {
      expect(screen.getByText(/Reconstructed/i)).toBeInTheDocument()
    })
    expect(
      screen.getByText(/not a record of what the site showed that week/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Predicted live/i)).not.toBeInTheDocument()
  })

  // ProvenanceNote gained a `compact` prop for Track Record's use (see
  // TrackRecord.test.tsx). The Leaderboard's call site passes nothing, so
  // its report card must render the full, unabridged text exactly as before.
  it('renders the full ProvenanceNote text on the report card, unaffected by the compact mode added for Track Record', async () => {
    mockFetch({ tournament: COMPLETED_TOURNAMENT_FIXTURE })
    renderLeaderboard(makeClient())

    await waitFor(() => expect(screen.getByText(/Predicted live/i)).toBeInTheDocument())
    expect(
      screen.getByText(/scored against the board recorded before play began, exactly as the site served it/i),
    ).toBeInTheDocument()
  })

  it('states the absence instead of falling back to a recomputation', async () => {
    mockFetch({
      tournament: COMPLETED_TOURNAMENT_FIXTURE,
      archived: { available: false, tournament_id: 3, tournament_name: 'The Open', outcomes: [] },
    })
    renderLeaderboard(makeClient())

    await waitFor(() => {
      expect(screen.getByText(/No pre-event board was pinned for this event/i)).toBeInTheDocument()
    })
    // No report card at all — not one quietly built from the live board.
    expect(screen.queryByText(/by win%/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Top-20 hits/i)).not.toBeInTheDocument()
    expect(screen.getByText(/not what was predicted beforehand/i)).toBeInTheDocument()
    // And no board either — the table is withheld rather than recomputed.
    expect(document.querySelector('tbody')).toBeNull()
    expect(screen.queryByText('Rory Birdie')).not.toBeInTheDocument()
  })

  // --- the table reads the same pinned board as the card ------------------

  it('renders the table from the pinned board, not the recomputation', async () => {
    mockFetch({ tournament: COMPLETED_TOURNAMENT_FIXTURE })
    renderLeaderboard(makeClient())

    await waitFor(() => expect(screen.getByText(/Predicted live/i)).toBeInTheDocument())

    const cells = Array.from(document.querySelectorAll('tbody tr')).map((r) =>
      Array.from(r.querySelectorAll('td')).map((c) => c.textContent?.trim()),
    )
    const tiger = cells.find((c) => c[1] === 'Tiger Chip')!
    // Archived win_prob is 31.0%; the live fixture says 7.0% for the same player.
    expect(tiger).toContain('31.0%')
    expect(tiger).not.toContain('7.0%')
    // Jordan Fade exists only on the archived board, not the live one.
    expect(screen.getByText('Jordan Fade')).toBeInTheDocument()
  })

  it('agrees with the report card on who the board favoured', async () => {
    mockFetch({ tournament: COMPLETED_TOURNAMENT_FIXTURE })
    renderLeaderboard(makeClient())

    await waitFor(() => expect(screen.getByText(/board #1 by win%/i)).toBeInTheDocument())

    // Sort by Win so the table's own ordering is comparable to the card's rank.
    screen.getByRole('button', { name: /Sort by Win/i }).click()
    await waitFor(() => {
      const first = document.querySelector('tbody tr')
      expect(first?.querySelectorAll('td')[1]?.textContent?.trim()).toBe('Tiger Chip')
    })
    // The card named Tiger #1 by win%; the table, reading the same board, agrees.
    expect(screen.getByText(/Tiger Chip · board #1 by win%/i)).toBeInTheDocument()
  })

  it('does not recompute a live board for a completed event', async () => {
    mockFetch({ tournament: COMPLETED_TOURNAMENT_FIXTURE })
    renderLeaderboard(makeClient())

    await waitFor(() => expect(screen.getByText(/Predicted live/i)).toBeInTheDocument())
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map(
      (c) => c[0] as string,
    )
    // /predictions/3/archived is expected; a bare /predictions/3 is not.
    expect(calls.some((u) => u.includes('/archived'))).toBe(true)
    expect(calls.some((u) => /\/predictions\/\d+(\?|$)/.test(u))).toBe(false)
  })

  it('carries the reconstruction caveat on a backfilled board table', async () => {
    mockFetch({
      tournament: COMPLETED_TOURNAMENT_FIXTURE,
      archived: { ...ARCHIVED_BOARD_FIXTURE, source: 'backfilled' },
    })
    renderLeaderboard(makeClient())

    await waitFor(() => expect(screen.getByText(/Reconstructed/i)).toBeInTheDocument())
    // The table still renders the pinned board, and the caveat sits above it.
    expect(screen.getByText('Jordan Fade')).toBeInTheDocument()
    expect(
      screen.getByText(/read from the prediction ledger. Not recomputed/i),
    ).toBeInTheDocument()
  })

  it('does not score make-cut on an event that had no cut', async () => {
    mockFetch({
      tournament: COMPLETED_TOURNAMENT_FIXTURE,
      archived: {
        ...ARCHIVED_BOARD_FIXTURE,
        event_had_a_cut: false,
        outcomes: ARCHIVED_BOARD_FIXTURE.outcomes.map((o) => ({ ...o, made_cut: null })),
      },
    })
    renderLeaderboard(makeClient())

    await waitFor(() => expect(screen.getByText(/Predicted live/i)).toBeInTheDocument())
    expect(screen.getByText(/no cut at this event/i)).toBeInTheDocument()
    expect(screen.queryByText(/always-guess/i)).not.toBeInTheDocument()
  })

  it('flags a board the model was not trained before', async () => {
    mockFetch({
      tournament: COMPLETED_TOURNAMENT_FIXTURE,
      archived: { ...ARCHIVED_BOARD_FIXTURE, out_of_sample: false },
    })
    renderLeaderboard(makeClient())

    await waitFor(() => {
      expect(screen.getByText(/not an out-of-sample result/i)).toBeInTheDocument()
    })
  })

  it('does not fetch an archived board for an event still in progress', async () => {
    mockFetch({ tournament: { ...TOURNAMENT_FIXTURE, status: 'in_progress' } })
    renderLeaderboard(makeClient())

    await waitFor(() => expect(screen.getAllByText(/Rory Birdie/).length).toBeGreaterThan(0))
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map(
      (c) => c[0] as string,
    )
    expect(calls.some((u) => u.includes('/archived'))).toBe(false)
  })

  // --- coverage tile (audit F3 / H6) -----------------------------------------
  // A board that cold-started the whole field must not look identical to a
  // healthy Path A board — dg_direct_count is what tells them apart.

  it('shows no coverage tile when /status is unreachable, not an error', async () => {
    mockFetch({ status: null })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getAllByText(/Rory Birdie/).length).toBeGreaterThan(0))
    expect(screen.queryByText(/priced by DataGolf/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/in-house model/i)).not.toBeInTheDocument()
  })

  it('distinguishes a healthy Path A board from full cold-start in the coverage tile', async () => {
    mockFetch({
      status: STATUS_FIXTURE,
      predictions: { ...PREDICTIONS_FIXTURE, dg_direct_count: 1, dg_fetch_status: 'ok' },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/1 of 2 priced by DataGolf/i)).toBeInTheDocument()
    })
    expect(
      screen.getByTitle(/1 of 2 players on this board were priced directly by DataGolf/i),
    ).toBeInTheDocument()

    // Same serving_strategy, same model_version_id — only dg_direct_count
    // differs. Before this fix these two boards were indistinguishable.
    mockFetch({
      status: STATUS_FIXTURE,
      predictions: { ...PREDICTIONS_FIXTURE, dg_direct_count: 0, dg_fetch_status: 'no_coverage' },
    })
    cleanup()
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/No DataGolf prices, in-house model only/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/priced by DataGolf/i)).not.toBeInTheDocument()
  })

  it('distinguishes a legitimate cold start from a broken DataGolf fetch', async () => {
    mockFetch({
      status: STATUS_FIXTURE,
      predictions: { ...PREDICTIONS_FIXTURE, dg_direct_count: 0, dg_fetch_status: 'fetch_failed' },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(/DataGolf prices unavailable, in-house model only/i),
      ).toBeInTheDocument()
    })
    expect(screen.getByTitle(/a degraded result, not a clean cold start/i)).toBeInTheDocument()
    expect(screen.queryByText(/No DataGolf prices/i)).not.toBeInTheDocument()
  })

  it('flags when a board omits coverage entirely under Path A', async () => {
    mockFetch({
      status: STATUS_FIXTURE,
      predictions: { ...PREDICTIONS_FIXTURE, dg_direct_count: null, dg_fetch_status: null },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Coverage not recorded/i)).toBeInTheDocument()
    })
  })

  it('does not claim DataGolf coverage when the serving strategy is something else', async () => {
    mockFetch({ status: { ...STATUS_FIXTURE, serving_strategy: 'stacked' } })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/In-house model, all players/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/priced by DataGolf/i)).not.toBeInTheDocument()
  })

  // --- small and no-cut fields (FedExCup playoffs) --------------------------
  // Playoff fields are 69, 50 and 30 players with no cut. Two things that are
  // fine at a 156-player field stop being fine there: the Make Cut column
  // reads 100.0% on every row, and "Top 20" stops being selective.
  describe('at a no-cut event', () => {
    // Every player at exactly 1.0 make_cut_prob is how DataGolf reports a
    // field with no 36-hole cut. Verified against all three archived playoff
    // boards; no event that did cut has any player at 1.0.
    const NO_CUT_FIXTURE = {
      ...PREDICTIONS_FIXTURE,
      outcomes: padField(PREDICTIONS_FIXTURE.outcomes, 30).map((o) => ({
        ...o,
        make_cut_prob: 1,
      })),
    }

    it('hides the Make Cut column', async () => {
      mockFetch({ predictions: NO_CUT_FIXTURE })
      renderLeaderboard(makeClient())
      await waitFor(() => expect(screen.getAllByText(/Rory Birdie/).length).toBeGreaterThan(0))

      expect(screen.queryByRole('button', { name: /Sort by Make Cut/i })).not.toBeInTheDocument()
      // The other four markets still have their headers.
      expect(screen.getByRole('button', { name: /Sort by Top 20/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /Sort by Win/i })).toBeInTheDocument()
    })

    it('keeps the Make Cut column at an event that does have a cut', async () => {
      mockFetch()
      renderLeaderboard(makeClient())
      await waitFor(() => expect(screen.getAllByText(/Rory Birdie/).length).toBeGreaterThan(0))
      expect(screen.getByRole('button', { name: /Sort by Make Cut/i })).toBeInTheDocument()
    })

    it('shows the empty-field state rather than inferring a no-cut event', async () => {
      // `every` is true for an empty array, so without the length guard an
      // upcoming event whose field is not published yet would read as no-cut.
      // No table renders at all in that state, so the guard's job is to keep
      // `eventHasACut` true for everything downstream of it (the drawer).
      mockFetch({ predictions: { ...PREDICTIONS_FIXTURE, outcomes: [] } })
      renderLeaderboard(makeClient())
      await waitFor(() =>
        expect(screen.getByText(/No field published for this event yet/i)).toBeInTheDocument(),
      )
      expect(screen.queryByRole('button', { name: /Sort by Top 20/i })).not.toBeInTheDocument()
    })

    it('falls back to Top 20 when the URL sorts by the hidden column', async () => {
      mockFetch({ predictions: NO_CUT_FIXTURE })
      render(
        <QueryClientProvider client={makeClient()}>
          <MemoryRouter initialEntries={['/leaderboard?sort=make_cut_prob']}>
            <Leaderboard />
          </MemoryRouter>
        </QueryClientProvider>,
      )
      await waitFor(() => expect(screen.getAllByText(/Rory Birdie/).length).toBeGreaterThan(0))

      // The Top 20 header carries the active-sort caret, so the table is not
      // sorted by a column the reader cannot see or un-sort.
      const top20 = screen.getByRole('button', { name: /Sort by Top 20/i })
      expect(top20.textContent).toMatch(/[▼▲]/)
    })

    it('suppresses the Sleeper tile and drops the grid to two tiles', async () => {
      mockFetch({ predictions: NO_CUT_FIXTURE })
      renderLeaderboard(makeClient())
      await waitFor(() => expect(screen.getByText('30 players')).toBeInTheDocument())

      expect(screen.queryByText(/Sleeper/i)).not.toBeInTheDocument()
      // Field tile survives, so the reader still sees why: it is a 30-man field.
      expect(screen.getByText('Field')).toBeInTheDocument()
    })
  })

  it('suppresses the Sleeper tile at a 50-player field', async () => {
    mockFetch({
      predictions: { ...PREDICTIONS_FIXTURE, outcomes: padField(SLEEPER_SEED, 50) },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getByText('50 players')).toBeInTheDocument())
    expect(screen.queryByText(/Sleeper/i)).not.toBeInTheDocument()
  })

  it('suppresses the Sleeper tile at a 69-player playoff field', async () => {
    mockFetch({
      predictions: { ...PREDICTIONS_FIXTURE, outcomes: padField(SLEEPER_SEED, 69) },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getByText('69 players')).toBeInTheDocument())
    expect(screen.queryByText(/Sleeper/i)).not.toBeInTheDocument()
  })

  it('shows the Sleeper tile at a standard 144-player field', async () => {
    mockFetch({
      predictions: { ...PREDICTIONS_FIXTURE, outcomes: padField(SLEEPER_SEED, 144) },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getByText('144 players')).toBeInTheDocument())
    expect(screen.getByText(/Longshot Lou · 40% Top 20 · 1% Win/i)).toBeInTheDocument()
  })
})
