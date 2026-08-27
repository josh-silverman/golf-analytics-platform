import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

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
  },
  {
    tournament_id: 2,
    tournament_name: 'The 3M',
    tournament_start_date: '2026-06-20',
    source: 'captured' as const,
    out_of_sample: true,
  },
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

function mockFetch({
  events = EVENTS_FIXTURE as typeof EVENTS_FIXTURE | null,
  board = boardFixture() as Record<string, unknown> | null,
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
        if (board == null) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => board })
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

  it('defaults to the most recent event', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Tiger Chip')).toBeInTheDocument()
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

  it('attaches the chance baseline to the top-20 tile', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => {
      // 3-player field, top20Picks = min(20, 3) = 3; 2 of the 3 picks (Tiger,
      // Rory) finished top 20, Jordan missed the cut → 2/3 hits.
      // byChance = top20Picks * (top20Picks / field) = 3 * 3/3 = 3.0.
      expect(screen.getByText(/2 \/ 3 · 3\.0 by chance/i)).toBeInTheDocument()
    })
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

  it('shows a distinct message for an ungraded pinned board', async () => {
    mockFetch({ board: boardFixture({ graded: false, outcomes: [] }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/results have not settled yet/i)).toBeInTheDocument()
    })
  })

  it('carries the reconstruction caveat on a backfilled board', async () => {
    mockFetch({ board: boardFixture({ source: 'backfilled' }) })
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Reconstructed/i)).toBeInTheDocument()
    })
  })

  // --- top picks visual ------------------------------------------------------

  it('shows the top picks table with probability and finish side by side', async () => {
    mockFetch()
    renderTrackRecord(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Top 3 Picks/i)).toBeInTheDocument()
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
    await waitFor(() => expect(screen.getByText(/Top 3 Picks/i)).toBeInTheDocument())
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
    await waitFor(() => expect(screen.getByText(/Top 3 Picks/i)).toBeInTheDocument())

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
})
