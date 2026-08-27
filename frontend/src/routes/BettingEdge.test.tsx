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

// A mixed market: Rory carries a real DataGolf book price, Tiger does not and
// was priced by the backend from the served probability itself. The board-level
// `odds_source` reads "datagolf" on the strength of Rory alone, which is exactly
// the flag the page must NOT use to describe Tiger's row or the market.
const BOARD_FIXTURE = {
  tournament_id: 7,
  tournament_name: 'The Masters',
  outcome_key: 'win_prob',
  n_positive_ev: 2,
  odds_source: 'datagolf',
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
      odds_source: 'datagolf',
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
      odds_source: 'model',
    },
  ],
}

// Every line fabricated, and the board flag agrees. Used to pin the all-synthetic
// wording, which must not promote the market on any axis.
const ALL_SYNTHETIC_FIXTURE = {
  ...BOARD_FIXTURE,
  odds_source: 'model',
  lines: BOARD_FIXTURE.lines.map((l) => ({ ...l, odds_source: 'model' })),
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
    expect(screen.getByRole('heading', { name: /Market Comparison/i })).toBeInTheDocument()
  })

  it('shows the player name in the table', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      // getAllByText because the name also appears in the SVG chart
      expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0)
    })
  })

  it('shows formatted American odds', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText('+600')).toBeInTheDocument()
    })
  })

  // --- no betting advice anywhere on the page ------------------------------
  // The page reports a disagreement between two probability sources and grades
  // nothing, so it must not carry staking, EV, or recommendation vocabulary.

  it('renders no expected-value, staking, or recommendation vocabulary', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0))

    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(/\+EV/)
    expect(text).not.toMatch(/Kelly/i)
    expect(text).not.toMatch(/EV \/ \$1/)
    expect(text).not.toMatch(/★/)
    expect(text).not.toMatch(/actionable/i)
    expect(text).not.toMatch(/¢/)
  })

  it('shows how many players are being compared, not how many are +EV', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Players compared:/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/\+EV lines/i)).not.toBeInTheDocument()
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

  // --- per-line odds provenance (audit F2) ---------------------------------

  it('shows only book-priced rows, never a synthetic label', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Book')).toBeInTheDocument()
    })
    // The board flag says "datagolf", but only one of the two lines is real —
    // and the fabricated one is dropped rather than labelled.
    expect(screen.getAllByText('Book')).toHaveLength(1)
    expect(screen.queryByText('Synthetic')).not.toBeInTheDocument()
  })

  it('states real-price coverage instead of promoting the whole market', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/1 of 2 lines are priced against a live sportsbook/i))
        .toBeInTheDocument()
    })
    // The old copy promoted a mixed market to "Live odds · best market" whenever
    // any single line was real.
    expect(screen.queryByText(/Live odds · best market/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Partial live odds/i)).toBeInTheDocument()
  })

  it('says the market is unavailable when no line has a book price', async () => {
    mockFetch({ board: ALL_SYNTHETIC_FIXTURE })
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/The books are not offering this market/i)).toBeInTheDocument()
    })
    // Distinct from "your filter is too tight" — telling the reader to lower the
    // filter would send them after data that does not exist this week.
    expect(screen.queryByText(/Lower the filter/i)).not.toBeInTheDocument()
    expect(screen.getByText('Synthetic odds')).toBeInTheDocument()
    expect(screen.queryByText('Book')).not.toBeInTheDocument()
    // No table at all, rather than a table of dashes.
    expect(document.querySelector('tbody tr')).toBeNull()
  })

  // --- a fabricated price is not a disagreement (audit F1) -----------------
  // A synthetic line's "price" is a function of the served probability itself,
  // so a row built on one compares the board against its own number. There is
  // nothing to show, so the row is dropped rather than blanked.

  function rowFor(name: string): string[] {
    const row = Array.from(document.querySelectorAll('tbody tr')).find((r) =>
      r.textContent?.includes(name),
    )
    return Array.from(row?.querySelectorAll('td') ?? []).map((c) =>
      (c.textContent ?? '').replace(/\s+/g, ' ').trim(),
    )
  }

  it('hides an unpriced player entirely rather than blanking their row', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getByText('Book')).toBeInTheDocument())

    // Tiger has no book price — he appears nowhere: not in the table, not in
    // the chart, not as a row of dashes.
    expect(screen.queryByText('Tiger Chip')).not.toBeInTheDocument()
    expect(rowFor('Tiger Chip')).toEqual([])
    expect(document.querySelectorAll('tbody tr')).toHaveLength(1)

    const plotted = Array.from(document.querySelectorAll('svg text')).map((t) => t.textContent)
    expect(plotted.some((t) => t?.includes('Rory Birdie'))).toBe(true)
    expect(plotted.some((t) => t?.includes('Tiger Chip'))).toBe(false)
  })

  it('accounts for the hidden players beneath the table', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getByText('Book')).toBeInTheDocument())
    // Their absence is stated, so a reader comparing this against the
    // leaderboard's field size can account for the difference.
    expect(
      screen.getByText(/1 player in this field has no sportsbook price and is not shown/i),
    ).toBeInTheDocument()
  })

  it('renders a priced row with the betting columns removed', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getByText('Book')).toBeInTheDocument())

    // # | Player | Board | Implied | Odds | Source | Edge  — seven columns, no
    // EV / $1 and no ½-Kelly.
    const rory = rowFor('Rory Birdie')
    expect(rory).toHaveLength(7)
    expect(rory[2]).toBe('18.0%')
    expect(rory[3]).toBe('14.0%')
    expect(rory[4]).toBe('+600')
    expect(rory[5]).toBe('Book')
    expect(rory[6]).toBe('+4.0%')
  })

  it('never renders the contaminated make-cut Brier figure', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0)
    })
    // README.md:166 — the make-cut skill figure is contaminated by no-cut events
    // and must not be quoted until re-measured.
    expect(document.body.textContent).not.toMatch(/Brier/i)
    expect(document.body.textContent).not.toMatch(/\+0\.2[45]/)
  })

  // --- attribution (audit F3 / H4) -----------------------------------------
  // Under Path A, "model probability" is frequently DataGolf's own number, so
  // the page must not claim a model-vs-market comparison unconditionally.

  it('labels the probability column "Board", not "Model"', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0))
    expect(screen.getByRole('columnheader', { name: 'Board' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Model' })).not.toBeInTheDocument()
  })

  it('does not claim an unconditional model-vs-market comparison', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0))
    // The old copy asserted "Where the model diverges from the market" as fact.
    expect(screen.queryByText(/Where the model diverges from the market/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Where the served board diverges from the market/i)).toBeInTheDocument()
    expect(
      screen.getByText(/DataGolf against its own feed, not the in-house model/i),
    ).toBeInTheDocument()
  })

  it('does not assert an unqualified "validated skill" claim', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0))
    expect(screen.queryByText(/validated skill/i)).not.toBeInTheDocument()
  })

  it('uses board-probability wording in the filter section, not model-probability', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0))
    expect(screen.getByText('Min. board probability')).toBeInTheDocument()
    expect(screen.queryByText(/model probability/i)).not.toBeInTheDocument()
  })
})
