import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ForwardTrackRecord } from '../lib/api/forwardTrackRecord'
import { TrackRecord } from './TrackRecord'

afterEach(cleanup)

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderTrackRecord(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TrackRecord />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const EVENTS_FIXTURE = [
  {
    tournament_id: 3,
    tournament_name: 'The Open',
    tournament_start_date: '2026-07-10',
    source: 'captured' as const,
    out_of_sample: true,
    graded: true,
  },
  {
    tournament_id: 2,
    tournament_name: 'The 3M',
    tournament_start_date: '2026-06-20',
    source: 'captured' as const,
    out_of_sample: true,
    graded: true,
  },
]

// The newest event is in-progress and ungraded, with an older graded event
// behind it — exercises the "skip to the most recent graded event" default.
const EVENTS_WITH_IN_PROGRESS_FIXTURE = [
  {
    tournament_id: 4,
    tournament_name: 'The Genesis',
    tournament_start_date: '2026-08-01',
    source: 'captured' as const,
    out_of_sample: true,
    graded: false,
  },
  ...EVENTS_FIXTURE,
]


function boardFixture(overrides: Record<string, unknown> = {}) {
  return {
    available: true,
    tournament_id: 3,
    tournament_name: 'The Open',
    tournament_start_date: '2026-07-10',
    source: 'captured',
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
        top_20_prob: 0.6,
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
        top_20_prob: 0.3,
        make_cut_prob: 0.35,
        final_position: null,
        made_cut: false,
      },
    ],
    ...overrides,
  }
}

// Mirrors the live record as of 2026-08-20: live captures + backfilled
// reconstructions, with per-provenance market aggregates and a settling
// footer still counting down. Reused from the old Leaderboard fixture (see
// git history) now that the aggregate lives on this page instead.
const TRACK_RECORD_FIXTURE: ForwardTrackRecord = {
  available: true,
  events: 9,
  players_graded: 1239,
  events_to_meaningful: 11,
  events_path_a: 9,
  events_cold_start_only: 0,
  events_regime_unknown: 0,
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
    // Neither headline market clears in the captured pool yet (both
    // ci_lower: null) — exercises the "neither" phrasing of conclusiveLine.
    {
      market: 'top_20_prob',
      n: 300,
      base_rate: 0.14,
      brier: 0.1,
      brier_skill: 0.02,
      ci_lower: null,
      ci_upper: null,
    },
    // win_prob is not a headline market and must not render in the block at
    // all, even though it's present in the API response.
    {
      market: 'win_prob',
      n: 300,
      base_rate: 0.008,
      brier: 0.007,
      brier_skill: 0.001,
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
    // Only make_cut clears here (ci_lower > 0); top_20 does not — exercises
    // the "only one" phrasing of conclusiveLine.
    {
      market: 'top_20_prob',
      n: 871,
      base_rate: 0.135,
      brier: 0.097,
      brier_skill: 0.03,
      ci_lower: -0.01,
      ci_upper: 0.08,
    },
  ],
}

function mockFetch({
  events = EVENTS_FIXTURE as typeof EVENTS_FIXTURE | null,
  board = boardFixture() as Record<string, unknown> | null,
  // Per-tournament-id override, keyed by id, checked before the single
  // `board` fallback above. Lets a test prove which event the page actually
  // selected by giving different ids visibly different boards.
  boardsById = {} as Record<number, Record<string, unknown> | null>,
  trackRecord = null as ForwardTrackRecord | null,
} = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      // Must precede the per-tournament check below: this is the literal
      // /predictions/archived list route, not /predictions/{id}/archived.
      if (url.endsWith('/predictions/archived')) {
        if (events == null) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => events })
      }
      if (url.includes('/archived')) {
        const match = /\/predictions\/(\d+)\/archived/.exec(url)
        const id = match ? Number(match[1]) : null
        const resolved = id != null && id in boardsById ? boardsById[id] : board
        if (resolved == null) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resolved })
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

describe('TrackRecord', () => {
  it('renders the heading immediately', () => {
    mockFetch()
    renderTrackRecord(makeClient())
    expect(screen.getByRole('heading', { name: /Track Record/i })).toBeInTheDocument()
  })

  it('shows the static trust line on every event, not just graded ones', async () => {
    mockFetch({ board: boardFixture({ graded: false, outcomes: [] }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(
          /Every prediction on this page was recorded before play began and has not been edited since/i,
        ),
      ).toBeInTheDocument()
    })
  })

  it('lists pinned events newest first in the picker', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /The Open/i })).toBeInTheDocument()
    })
    const options = screen.getAllByRole('option') as HTMLOptionElement[]
    expect(options[0].textContent).toMatch(/The Open/)
    expect(options[1].textContent).toMatch(/The 3M/)
  })

  it('defaults to the most recent event when it is graded', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Tiger Chip')).toBeInTheDocument()
    })
  })

  // --- default event: most recent GRADED event, not most recent pinned ------

  it('skips an in-progress newest event and defaults to the most recent graded one', async () => {
    mockFetch({
      events: EVENTS_WITH_IN_PROGRESS_FIXTURE,
      boardsById: {
        4: boardFixture({ tournament_id: 4, graded: false, outcomes: [] }),
        3: boardFixture(),
      },
    })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      // Event 3's board (The Open) rendered, not event 4's (the newest, ungraded).
      expect(screen.getByText('Tiger Chip')).toBeInTheDocument()
    })
    expect(screen.getByRole('combobox')).toHaveValue('3')
  })

  it('falls back to the newest pinned board when nothing is graded yet', async () => {
    mockFetch({
      events: EVENTS_WITH_IN_PROGRESS_FIXTURE.map((e) => ({ ...e, graded: false })),
      boardsById: { 4: boardFixture({ tournament_id: 4, graded: false, outcomes: [] }) },
    })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toHaveValue('4')
    })
    // Ungraded, so the "not settled yet" message shows rather than a report card.
    expect(screen.getByText(/results have not settled yet/i)).toBeInTheDocument()
  })

  it('lets an explicit ?event= selection override the graded default', async () => {
    mockFetch({
      events: EVENTS_WITH_IN_PROGRESS_FIXTURE,
      boardsById: {
        4: boardFixture({ tournament_id: 4, graded: false, outcomes: [] }),
        3: boardFixture(),
      },
    })
    render(
      <QueryClientProvider client={makeClient()}>
        <MemoryRouter initialEntries={['/track-record?event=4']}>
          <TrackRecord />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toHaveValue('4')
    })
    // Event 4 is ungraded, and the explicit pick still wins over the default.
    expect(screen.getByText(/results have not settled yet/i)).toBeInTheDocument()
  })

  it('an ungraded event stays selectable in the picker even though it is never the default', async () => {
    mockFetch({ events: EVENTS_WITH_IN_PROGRESS_FIXTURE })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /The Genesis/i })).toBeInTheDocument()
    })
  })

  it('says the record is empty when no events are pinned', async () => {
    mockFetch({ events: [] })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/starts once boards are pinned/i)).toBeInTheDocument()
    })
  })

  // --- report card, reusing the Leaderboard's baselines ---------------------

  it('shows the winner tile with their board rank', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Tiger Chip · board #1 by win%/i)).toBeInTheDocument()
    })
  })

  // --- Top 20 headline sentence, replacing the old tile ---------------------
  // No adjective, no verdict: the same template must read honestly whether
  // the week beat the baseline or fell short of it.

  it('states the Top 20 result and its rounded chance baseline in one sentence', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => {
      // 3-player field, top20Picks = min(20, 3) = 3; 2 of the 3 highest-rated
      // (Tiger, Rory) finished top 20, Jordan missed the cut → 2 hits.
      // byChance = top20Picks * (top20Picks / field) = 3 * 3/3 = 3.0 → "about 3".
      expect(
        screen.getByText(
          /2 of the board's 3 highest-rated players finished inside the Top 20\. In a 3-player field, random guessing would land about 3\./i,
        ),
      ).toBeInTheDocument()
    })
  })

  it('never claims the board "picked" players, in the headline sentence specifically', async () => {
    // "Picks" legitimately appears elsewhere on the page (the unrelated,
    // unchanged TopPicksTable heading), so this checks the headline
    // sentence's own text rather than the whole document.
    mockFetch()
    renderTrackRecord(makeClient())
    const headline = await screen.findByText(/highest-rated players finished inside the Top 20/i)
    expect(headline.textContent).not.toMatch(/picks|picked/i)
  })

  it('reads without an adjective or verdict on a below-baseline week', async () => {
    // A 156-player field where only 2 of the board's top 20 finished top 20,
    // against a chance baseline of 20 * 20/156 ≈ 2.6 → "about 3". The result
    // (2) is below the baseline (3), and the sentence must not editorialize
    // about that: no "weak", "poor", "disappointing" or similar.
    const outcomes = Array.from({ length: 156 }, (_, i) => ({
      player_id: i + 1,
      player_name: `P${i + 1}`,
      win_prob: 0.3 - i * 0.001,
      top_5_prob: 0.5 - i * 0.002,
      top_10_prob: 0.6 - i * 0.002,
      top_20_prob: 0.9 - i * 0.004,
      make_cut_prob: 0.95 - i * 0.004,
      final_position: i < 2 ? i + 1 : i < 40 ? 25 + i : null,
      made_cut: i < 80,
    }))
    mockFetch({ board: boardFixture({ outcomes }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(
          /2 of the board's 20 highest-rated players finished inside the Top 20\. In a 156-player field, random guessing would land about 3\./i,
        ),
      ).toBeInTheDocument()
    })
    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(/weak|poor|disappointing|strong week|solid showing|struggled/i)
  })

  // --- field size in the headline (FedExCup playoffs) ----------------------
  // Top 20 stays the metric at every field size, so the same "20 highest-rated"
  // number means very different things at 30 players and at 156. Naming the
  // field size is what lets a reader tell those apart.
  //
  // Builds a field of `size` where `hits` of the board's top 20 finished
  // inside the top 20, so each case below states an exact expected sentence.
  function fieldOf(size: number, hits: number) {
    return Array.from({ length: size }, (_, i) => ({
      player_id: i + 1,
      player_name: `P${i + 1}`,
      win_prob: 0.3 - i * 0.001,
      top_5_prob: 0.5 - i * 0.002,
      top_10_prob: 0.6 - i * 0.002,
      top_20_prob: 0.9 - i * 0.004,
      make_cut_prob: 0.95 - i * 0.004,
      // The board's top 20 by top_20_prob is exactly players 0..19, so the
      // first `hits` of them finish inside the top 20 and the rest do not.
      final_position: i < hits ? i + 1 : 21 + i,
      made_cut: true,
    }))
  }

  it('names the field size at a 30-player playoff field', async () => {
    // 20 picks, each with a 20/30 chance: 20 * (20/30) = 13.3 -> "about 13".
    mockFetch({ board: boardFixture({ outcomes: fieldOf(30, 13) }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(
          /13 of the board's 20 highest-rated players finished inside the Top 20\. In a 30-player field, random guessing would land about 13\./i,
        ),
      ).toBeInTheDocument()
    })
  })

  it('names the field size at a 50-player playoff field', async () => {
    // 20 * (20/50) = 8.
    mockFetch({ board: boardFixture({ outcomes: fieldOf(50, 10) }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(
          /10 of the board's 20 highest-rated players finished inside the Top 20\. In a 50-player field, random guessing would land about 8\./i,
        ),
      ).toBeInTheDocument()
    })
  })

  it('names the field size at a standard field too, not only small ones', async () => {
    // 20 * (20/156) = 2.6 -> "about 3". The clause is present at every size so
    // the sentence keeps one shape week to week.
    mockFetch({ board: boardFixture({ outcomes: fieldOf(156, 7) }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(
          /7 of the board's 20 highest-rated players finished inside the Top 20\. In a 156-player field, random guessing would land about 3\./i,
        ),
      ).toBeInTheDocument()
    })
  })

  it('reads without a verdict when a small field matches chance exactly', async () => {
    // The honesty case: at 30 players, 13 hits IS the chance baseline, so the
    // sentence reports a week that beat nothing. It must still just state the
    // two numbers.
    mockFetch({ board: boardFixture({ outcomes: fieldOf(30, 13) }) })
    renderTrackRecord(makeClient())
    const headline = await screen.findByText(/highest-rated players finished inside the Top 20/i)
    expect(headline.textContent).not.toMatch(
      /weak|poor|disappointing|strong|solid|struggled|only|just|merely|barely|no better/i,
    )
    expect(headline.textContent).not.toMatch(/—/)
  })

  it('renders no headline sentence when there is no report card to draw one from', async () => {
    // Zero outcomes means computeReportCard returns null entirely (not a
    // report card with a null baseline), so the headline block does not
    // render at all rather than printing "about null" or similar.
    mockFetch({ board: boardFixture({ outcomes: [] }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /The Open/i })).toBeInTheDocument()
    })
    expect(screen.queryByText(/highest-rated players/i)).not.toBeInTheDocument()
  })

  it('attaches the always-guess baseline to the make-cut tile', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => {
      // 2 of 3 made the cut → cutBaseRate = 2/3 = 66.7%; both graded players
      // predicted >=50% make-cut and both made it → cutAcc = 100%.
      expect(screen.getByText(/100\.0% · 66\.7% always-guess/i)).toBeInTheDocument()
    })
  })

  it('shows the Top-20 headline sentence and Winner tile, no separate Top-20 tile', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText('Tiger Chip')).toBeInTheDocument())
    expect(screen.queryByText('Top-20 hits')).not.toBeInTheDocument()
  })

  it('omits the make-cut tile entirely on a no-cut event, showing only Winner', async () => {
    mockFetch({ board: boardFixture({ event_had_a_cut: false }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Tiger Chip · board #1 by win%/i)).toBeInTheDocument()
    })
    expect(screen.queryByText('Make-cut accuracy')).not.toBeInTheDocument()
    // The headline sentence is unaffected by the cut status: Top 20 finishes
    // come from final_position, which a no-cut event still has.
    expect(screen.getByText(/highest-rated players finished inside the Top 20/i)).toBeInTheDocument()

    // The lone Winner tile must not stretch full width: bare `grid-cols-1`
    // is one column at 100% width, not a bounded card. The container caps
    // its own width instead of gaining a second column.
    const winnerTile = screen.getByText('Winner').closest('div.grid') as HTMLElement
    expect(winnerTile.className).toMatch(/sm:max-w-xs/)
    expect(winnerTile.className).not.toMatch(/sm:grid-cols-2/)
  })

  it('shows a distinct message for an ungraded pinned board', async () => {
    mockFetch({ board: boardFixture({ graded: false, outcomes: [] }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/results have not settled yet/i)).toBeInTheDocument()
    })
  })

  it('carries the reconstruction caveat on a backfilled board', async () => {
    // Track Record renders ProvenanceNote in compact mode, which drops the
    // "Reconstructed" label (the top trust line already carries that claim)
    // but must still carry the one thing the compact form cannot drop: that
    // this board was rebuilt after the fact, not recorded live.
    mockFetch({ board: boardFixture({ source: 'backfilled' }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Rebuilt after the event/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/Reconstructed/i)).not.toBeInTheDocument()
  })

  it('shows only player count and pin date on a captured board, no restated trust claim', async () => {
    mockFetch({ board: boardFixture({ source: 'captured' }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/players on the board/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/Predicted live/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/scored against the board recorded before play began/i)).not.toBeInTheDocument()
  })

  // --- top picks visual ------------------------------------------------------

  it('shows the top picks table with probability and finish side by side', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Top 3 by Top 20 Probability/i)).toBeInTheDocument()
    })
    // Tiger: 81.0% top-20 prob, finished 1st.
    const row = Array.from(document.querySelectorAll('tbody tr')).find((r) =>
      r.textContent?.includes('Tiger Chip'),
    )
    const cells = Array.from(row?.querySelectorAll('td') ?? []).map((c) => c.textContent)
    expect(cells).toContain('81.0%')
    expect(cells).toContain('1')
  })

  it('ranks picks by Top 20 probability, not win probability', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText(/Top 3 by Top 20 Probability/i)).toBeInTheDocument())
    const names = Array.from(document.querySelectorAll('tbody tr')).map(
      (r) => r.querySelectorAll('td')[1]?.textContent,
    )
    // Sorted by top_20_prob desc: Tiger .81, Rory .60, Jordan .30 — same order
    // win_prob would give here, so this alone doesn't distinguish the sorts;
    // it does confirm the ordering is at least consistent with top_20_prob.
    expect(names).toEqual(['Tiger Chip', 'Rory Birdie', 'Jordan Fade'])
  })

  // --- the hard rule: no pass/fail styling on an individual pick ------------
  // A low probability that didn't happen is the number working correctly,
  // not a miss. No row may be styled to imply otherwise.

  it('never marks an individual pick as right or wrong', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText(/Top 3 by Top 20 Probability/i)).toBeInTheDocument())

    // Jordan Fade missed the cut despite the lowest probability on the board,
    // and Tiger Chip won outright — the two most different outcomes possible.
    // Both rows must render in identical neutral styling: no per-row class
    // keyed to whether the outcome happened, no pass/fail icon.
    const rows = Array.from(document.querySelectorAll('tbody tr'))
    expect(rows.length).toBeGreaterThan(0)
    const rowClassSets = rows.map((row) => row.className)
    expect(new Set(rowClassSets).size).toBe(1) // every row shares one class string
    for (const row of rows) {
      expect(row.querySelector('[class*="positive"]')).toBeNull()
      expect(row.querySelector('[class*="negative"]')).toBeNull()
      expect(row.textContent).not.toMatch(/[✓✔✗✘×]/)
    }
  })

  it('encodes the probability bar from top_20_prob alone, identical for a hit and a miss at the same probability', async () => {
    // Two players at the SAME top_20_prob with OPPOSITE outcomes: one won,
    // one missed the cut. The bar must not be able to tell them apart.
    mockFetch({
      board: boardFixture({
        outcomes: [
          {
            player_id: 1,
            player_name: 'Hit Player',
            win_prob: 0.1,
            top_5_prob: 0.2,
            top_10_prob: 0.3,
            top_20_prob: 0.34,
            make_cut_prob: 0.8,
            final_position: 1,
            made_cut: true,
          },
          {
            player_id: 2,
            player_name: 'Miss Player',
            win_prob: 0.1,
            top_5_prob: 0.2,
            top_10_prob: 0.3,
            top_20_prob: 0.34,
            make_cut_prob: 0.8,
            final_position: null,
            made_cut: false,
          },
        ],
      }),
    })
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText('Hit Player')).toBeInTheDocument())

    const rows = Array.from(document.querySelectorAll('tbody tr'))
    const bars = rows.map((row) => row.querySelector('td div div') as HTMLElement)
    expect(bars).toHaveLength(2)
    // Same probability, so the same inline width, regardless of who hit.
    expect(bars[0].style.width).toBe(bars[1].style.width)
    expect(bars[0].style.width).toBe('34%')
  })

  it('scales the bar width monotonically with top_20_prob', async () => {
    mockFetch({
      board: boardFixture({
        outcomes: [
          { player_id: 1, player_name: 'High', win_prob: 0.2, top_5_prob: 0.4, top_10_prob: 0.6, top_20_prob: 0.8, make_cut_prob: 0.9, final_position: 5, made_cut: true },
          { player_id: 2, player_name: 'Low', win_prob: 0.05, top_5_prob: 0.1, top_10_prob: 0.15, top_20_prob: 0.2, make_cut_prob: 0.5, final_position: 40, made_cut: true },
        ],
      }),
    })
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText('High')).toBeInTheDocument())

    const rows = Array.from(document.querySelectorAll('tbody tr'))
    const bars = rows.map((row) => row.querySelector('td div div') as HTMLElement)
    expect(parseFloat(bars[0].style.width)).toBeGreaterThan(parseFloat(bars[1].style.width))
  })

  // --- overall record (aggregate forward track record) ----------------------
  // Moved here from the Leaderboard, which now only links to it.

  it('renders both provenance blocks with their own event and player counts', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_FIXTURE })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Overall record')).toBeInTheDocument()
    })
    // Separate blocks, each with its own event and player count. The
    // captured n of 2 must be visible, not pooled away. Plain-language
    // headings ("Recorded before play" / "Rebuilt afterwards") replaced the
    // internal "Predicted live" / "Reconstructed" terms.
    expect(screen.getByText(/Recorded before play · 2 events, 303 players graded/i)).toBeInTheDocument()
    expect(screen.getByText(/Rebuilt afterwards · 7 events, 936 players graded/i)).toBeInTheDocument()
  })

  it('shows only Make cut and Top 20, never the other three markets', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_FIXTURE })
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText('Overall record')).toBeInTheDocument())
    // Scoped to this section specifically (not a bare `document.querySelector`,
    // which is ambiguous whenever more than one <section> exists on the page).
    const section = screen.getByText('Overall record').closest('section')
    // Both headline markets appear, once per provenance block.
    expect(section?.textContent).toMatch(/Make cut/)
    expect(section?.textContent).toMatch(/Top 20/)
    // win_prob is present in the fixture's markets_captured but must not
    // render, nor Top 10 / Top 5.
    expect(section?.textContent).not.toMatch(/\bWin\b/)
    expect(section?.textContent).not.toMatch(/Top 10/)
    expect(section?.textContent).not.toMatch(/Top 5/)
  })

  it('states which markets are conclusive in one line instead of per-figure flags', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_FIXTURE })
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText('Overall record')).toBeInTheDocument())
    // Captured pool: neither headline market clears (both ci_lower: null).
    expect(
      screen.getByText(/Neither market is conclusive yet at this sample size/i),
    ).toBeInTheDocument()
    // Backfilled pool: only Make cut clears.
    expect(
      screen.getByText(/Only Make cut is conclusive at this sample size/i),
    ).toBeInTheDocument()
    // The old per-figure hedge is gone entirely.
    expect(screen.queryByText(/\(too early to say\)/i)).not.toBeInTheDocument()
  })

  it('keeps the per-figure baseline tooltip available on hover', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_FIXTURE })
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText('Overall record')).toBeInTheDocument())
    // The reconstructed block's Make cut figure clears; its tooltip should
    // explain the threshold even though the visible hedge text is gone.
    expect(
      screen.getByTitle(/Ahead of the field-average baseline by more than the week-to-week swing/i),
    ).toBeInTheDocument()
  })

  it('keeps the live and reconstructed pools visually separate, never pooled', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_FIXTURE })
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText('Overall record')).toBeInTheDocument())
    // The reconstruction disclaimer states what backfills are, on the
    // reconstructed block only.
    expect(
      screen.getByText(/not a record of what the site showed those weeks/i),
    ).toBeInTheDocument()
    // The baseline is named once, above both blocks.
    expect(
      screen.getByText(/predicting the field average for every player/i),
    ).toBeInTheDocument()
  })

  it('shows the settling footer as a visible line when the target is not yet met', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_FIXTURE })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      // "a number we chose, not a statistical threshold" replaced the
      // internal phrase "rule-of-thumb sample size".
      expect(
        screen.getByText(
          /About 11 more completed events to reach this page's 20-event target \(a number we chose, not a statistical threshold\)/i,
        ),
      ).toBeInTheDocument()
    })
  })

  it('omits the settling footer once the target sample size is met', async () => {
    mockFetch({ trackRecord: { ...TRACK_RECORD_FIXTURE, events_to_meaningful: 0 } })
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText('Overall record')).toBeInTheDocument())
    expect(screen.queryByText(/more completed events/i)).not.toBeInTheDocument()
  })

  it('surfaces the regime caveat as a tooltip, not a visible line', async () => {
    // 1 real Path A board + 1 cold-start-only + 1 unrecorded: the aggregate
    // is not measuring a single system, so a marker must appear, but the
    // full explanation should be on hover only.
    mockFetch({
      trackRecord: {
        ...TRACK_RECORD_FIXTURE,
        events_path_a: 1,
        events_cold_start_only: 1,
        events_regime_unknown: 1,
      },
    })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/mixed serving configurations/i)).toBeInTheDocument()
    })
    // The full explanation is not printed as its own visible line.
    expect(screen.queryByText(/pools more than one serving configuration/i)).not.toBeInTheDocument()
    expect(
      screen.getByTitle(/1 served cold-start only and 1 of unrecorded coverage out of 3/i),
    ).toBeInTheDocument()
  })

  it('omits the regime marker entirely when every graded board ran one regime', async () => {
    mockFetch({
      trackRecord: { ...TRACK_RECORD_FIXTURE, events_path_a: 9, events_cold_start_only: 0, events_regime_unknown: 0 },
    })
    renderTrackRecord(makeClient())
    await waitFor(() => expect(screen.getByText('Overall record')).toBeInTheDocument())
    expect(screen.queryByText(/mixed serving configurations/i)).not.toBeInTheDocument()
  })

  it('omits the overall record section entirely when the record is unavailable', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    // The per-week view still loads normally.
    await waitFor(() => {
      expect(screen.getByText(/Tiger Chip · board #1 by win%/i)).toBeInTheDocument()
    })
    expect(screen.queryByText('Overall record')).not.toBeInTheDocument()
  })

  it('renders the per-week report card above the overall record, unchanged', async () => {
    mockFetch({ trackRecord: TRACK_RECORD_FIXTURE })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Tiger Chip · board #1 by win%/i)).toBeInTheDocument()
    })
    await waitFor(() => expect(screen.getByText('Overall record')).toBeInTheDocument())
    // The per-week winner tile still appears earlier in the document than
    // the aggregate section, so the headline view is not displaced.
    const winnerText = screen.getByText(/Tiger Chip · board #1 by win%/i)
    const overallHeading = screen.getByText('Overall record')
    expect(
      winnerText.compareDocumentPosition(overallHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })
})
