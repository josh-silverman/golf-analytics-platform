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

  it('renders too-early markets when the CI is null instead of hiding the widget', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_PROVISIONAL_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Forward out-of-sample track record/i)).toBeInTheDocument()
    })
    // Both markets in the fixture have ci_lower: null, so both should render
    // as "too early to say" rather than being filtered out.
    expect(screen.getAllByText('(too early to say)')).toHaveLength(2)
    expect(
      screen.getByText(/About 18 more completed events to reach this page's 20-event rule-of-thumb/i),
    ).toBeInTheDocument()
    // Neither market clears the baseline yet, so the summary must not claim
    // the served board is ahead on anything.
    expect(
      screen.getByText(/Too early to say whether the served board beats the field-average/i),
    ).toBeInTheDocument()
  })

  it('splits the record into live-capture and reconstructed blocks with their own n', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_SPLIT_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Forward out-of-sample track record/i)).toBeInTheDocument()
    })
    // The summary leads with what the record is, then what it shows.
    expect(
      screen.getByText(/9 completed events graded: 2 recorded live before play, 7 reconstructed/i),
    ).toBeInTheDocument()
    // Separate blocks, each with its own event and player count. The captured
    // n of 2 must be visible, not pooled away.
    expect(screen.getByText(/Predicted live · 2 events, 303 players/i)).toBeInTheDocument()
    expect(screen.getByText(/Reconstructed · 7 events, 936 players/i)).toBeInTheDocument()
    // The reconstruction disclaimer states what backfills are.
    expect(
      screen.getByText(/not a record of what the site showed those weeks/i),
    ).toBeInTheDocument()
    // The baseline is named where the numbers are.
    expect(
      screen.getByText(/predicting the field average for every player/i),
    ).toBeInTheDocument()
    // The settling footer says which pool each estimate applies to, and no
    // longer implies "settle" is a calculated statistical threshold.
    expect(
      screen.getByText(
        /About 11 more completed events to reach this page's 20-event rule-of-thumb sample size \(a chosen target, not a calculated threshold\); the live-only record needs about 18 more/i,
      ),
    ).toBeInTheDocument()
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

  it('summarizes which markets clear the baseline in plain language', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_MIXED_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Forward out-of-sample track record/i)).toBeInTheDocument()
    })
    // make-cut and top-20 have ci_lower > 0; win does not. The claim is about
    // the served board, named baseline, not "the model".
    expect(
      screen.getByText(
        /The served board is ahead of the field-average baseline on Make cut and Top 20/i,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('(too early to say)')).toBeInTheDocument()
  })

  // --- "How to read this board" derives from the same signal as the widget
  // above it, so the two cannot disagree (audit F3 / H7) ---------------------

  it('claims a market is ahead only when the record above says so', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_MIXED_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getByText('How to read this board')).toBeInTheDocument())
    // Both make_cut_prob and top_20_prob clear (ci_lower > 0) in this fixture.
    expect(
      screen.getByText(
        /ranked by Top 20 and Make Cut — both currently ahead of the field-average baseline/i,
      ),
    ).toBeInTheDocument()
  })

  it('does not claim either market is ahead while the record says too early', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_PROVISIONAL_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getByText('How to read this board')).toBeInTheDocument())
    // Both markets in this fixture have ci_lower: null → neither clears.
    expect(
      screen.getByText(
        /ranked by Top 20 and Make Cut, the widest markets on the board — the record above has not yet shown either one ahead/i,
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/currently ahead of the/i)).not.toBeInTheDocument()
  })

  it('hedges the ranking claim when the record is unavailable', async () => {
    mockFetch({ trackRecord: null })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getByText('How to read this board')).toBeInTheDocument())
    expect(
      screen.getByText(/ranked by Top 20 and Make Cut, the widest markets on the board, while the live record above builds up/i),
    ).toBeInTheDocument()
  })

  it('does not claim an unqualified "most reliable" market in the Win tooltip', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_PROVISIONAL_FIXTURE })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getByText('How to read this board')).toBeInTheDocument())
    const winHeader = screen.getByRole('button', { name: /Sort by Win/i })
    expect(winHeader.getAttribute('title')).not.toMatch(/most reliable signal/i)
    expect(winHeader.getAttribute('title')).toMatch(/see the live record above/i)
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
    expect(screen.queryByText('How to read this board')).not.toBeInTheDocument()
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

  // --- serving provenance (audit F3 / H6) -----------------------------------
  // A board that cold-started the whole field must not look identical to a
  // healthy Path A board — dg_direct_count is what tells them apart, and
  // /status is what shows the registry can carry a different version id.

  it('shows nothing when /status is unreachable, not an error', async () => {
    mockFetch({ status: null })
    renderLeaderboard(makeClient())
    await waitFor(() => expect(screen.getAllByText(/Rory Birdie/).length).toBeGreaterThan(0))
    expect(screen.queryByText(/Registry-active model/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Path A/i)).not.toBeInTheDocument()
  })

  it('distinguishes a healthy Path A board from full cold-start with the same badge family', async () => {
    mockFetch({
      status: STATUS_FIXTURE,
      predictions: { ...PREDICTIONS_FIXTURE, dg_direct_count: 1, dg_fetch_status: 'ok' },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Path A · 1\/2 direct/i)).toBeInTheDocument()
    })
    expect(screen.getByTitle(/1 of 2 players on this board were priced directly by DataGolf/i)).toBeInTheDocument()

    // Same serving_strategy, same model_version_id — only dg_direct_count
    // differs. Before this fix these two boards were indistinguishable.
    mockFetch({
      status: STATUS_FIXTURE,
      predictions: { ...PREDICTIONS_FIXTURE, dg_direct_count: 0, dg_fetch_status: 'no_coverage' },
    })
    cleanup()
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Path A · cold-started \(no coverage\)/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/1\/2 direct/i)).not.toBeInTheDocument()
  })

  it('distinguishes a legitimate cold start from a broken DataGolf fetch', async () => {
    mockFetch({
      status: STATUS_FIXTURE,
      predictions: { ...PREDICTIONS_FIXTURE, dg_direct_count: 0, dg_fetch_status: 'fetch_failed' },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Path A · fetch problem/i)).toBeInTheDocument()
    })
    expect(screen.getByTitle(/a degraded result, not a clean cold start/i)).toBeInTheDocument()
    expect(screen.queryByText(/no coverage\)/i)).not.toBeInTheDocument()
  })

  it('flags when a board omits coverage entirely under Path A', async () => {
    mockFetch({
      status: STATUS_FIXTURE,
      predictions: { ...PREDICTIONS_FIXTURE, dg_direct_count: null, dg_fetch_status: null },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Path A · coverage unknown/i)).toBeInTheDocument()
    })
  })

  it('does not claim Path A coverage when the serving strategy is something else', async () => {
    mockFetch({ status: { ...STATUS_FIXTURE, serving_strategy: 'stacked' } })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(screen.getByText('stacked')).toBeInTheDocument()
    })
    expect(screen.queryByText(/Path A/i)).not.toBeInTheDocument()
  })

  it('flags when a board is stamped with a different model id than the registry reports', async () => {
    mockFetch({
      status: STATUS_FIXTURE, // v3_20260620
      predictions: {
        ...PREDICTIONS_FIXTURE,
        model_version_id: 'path_a@v2-cold', // different id, same board
        dg_direct_count: 1,
        dg_fetch_status: 'ok',
      },
    })
    renderLeaderboard(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(/this board is stamped path_a@v2-cold, a different id/i),
      ).toBeInTheDocument()
    })
  })
})
