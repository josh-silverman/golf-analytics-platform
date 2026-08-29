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

// Dates are computed relative to now, not hardcoded. The page suppresses the
// whole comparison once an event has started (`comparisonIsMeaningful`), so a
// fixed date would silently roll into the suppressed state as real time passes
// and fail this suite for a reason that has nothing to do with the code. The
// suite mocks no system time, so relative dates are what keeps it honest.
function isoDaysFromNow(days: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

const TOURNAMENT_FIXTURE = {
  id: 7,
  name: 'The Masters',
  season: 2026,
  start_date: isoDaysFromNow(5),
  end_date: isoDaysFromNow(8),
  status: 'upcoming',
  course_id: 1,
  purse: 18_000_000,
  field_strength: null,
}

// The same event, under way: play has started, so there is nothing to compare.
const UNDERWAY_TOURNAMENT_FIXTURE = {
  ...TOURNAMENT_FIXTURE,
  start_date: isoDaysFromNow(-1),
  end_date: isoDaysFromNow(2),
  status: 'in_progress',
}

// A mixed market: Rory carries a real DataGolf book price, Tiger does not and
// was priced by the backend from the served probability itself. The board-level
// `odds_source` reads "datagolf" on the strength of Rory alone, which is exactly
// the flag the page must NOT use to describe Tiger's row or the market.
const BOARD_FIXTURE = {
  tournament_id: 7,
  tournament_name: 'The Masters',
  outcome_key: 'win_prob',
  odds_source: 'datagolf',
  lines: [
    {
      player_id: 1,
      player_name: 'Rory Birdie',
      model_prob: 0.18,
      implied_prob: 0.14,
      american_odds: 600,
      edge: 0.04,
      odds_source: 'datagolf',
    },
    {
      player_id: 2,
      player_name: 'Tiger Chip',
      model_prob: 0.12,
      implied_prob: 0.15,
      american_odds: 500,
      edge: -0.03,
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

// Returns the stubbed fetch so a test can assert on which endpoints were
// actually called, not just on what rendered.
function mockFetch({
  tournament = TOURNAMENT_FIXTURE as Record<string, unknown> | null,
  board = BOARD_FIXTURE as typeof BOARD_FIXTURE | null,
} = {}) {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
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
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
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
    // The opening line states what the page shows, not who made which side of it.
    expect(
      screen.getByText(/Board probabilities against book-implied odds for the current field/i),
    ).toBeInTheDocument()
    // The Path A attribution survives, condensed, next to the market picker.
    expect(
      screen.getByText(/DataGolf against its own feed, not an independent comparison/i),
    ).toBeInTheDocument()
  })

  it('states the page is not a recommendation, near the opening line', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0))
    expect(
      screen.getByText(/Nothing here is graded, so none of it is a recommendation/i),
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

  // --- headline "biggest disagreement" callout -------------------------------
  // States the fact only: which player, how many points, which direction.
  // No adjective, no betting language, no implication the board is right.

  const BIGGEST_DISAGREEMENT_FIXTURE = {
    ...BOARD_FIXTURE,
    lines: [
      {
        player_id: 1,
        player_name: 'Reitan, Kristoffer',
        model_prob: 0.34,
        implied_prob: 0.12,
        american_odds: 250,
        edge: 0.22, // +22 points, the largest absolute gap
        odds_source: 'datagolf',
      },
      {
        player_id: 2,
        player_name: 'Burns, Sam',
        model_prob: 0.05,
        implied_prob: 0.14,
        american_odds: 400,
        edge: -0.09, // -9 points
        odds_source: 'datagolf',
      },
      {
        player_id: 3,
        player_name: 'Small Gap',
        model_prob: 0.2,
        implied_prob: 0.22,
        american_odds: 350,
        edge: -0.02, // under the 5-point floor, must never be picked
        odds_source: 'datagolf',
      },
      {
        player_id: 4,
        player_name: 'Synthetic Longshot',
        model_prob: 0.02,
        implied_prob: 0.5, // huge gap, but not a real price and must be ignored
        american_odds: 100,
        edge: -0.48,
        odds_source: 'model',
      },
    ],
  }

  it('names the player with the largest positive gap, board above the market', async () => {
    mockFetch({
      board: {
        ...BIGGEST_DISAGREEMENT_FIXTURE,
        lines: BIGGEST_DISAGREEMENT_FIXTURE.lines.filter((l) => l.player_id !== 2),
      },
    })
    renderEdge(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(/Biggest disagreement: Reitan, Kristoffer\. The board has him 22 points above the market\./i),
      ).toBeInTheDocument()
    })
  })

  it('names the player with the largest negative gap, board below the market', async () => {
    mockFetch({
      board: {
        ...BIGGEST_DISAGREEMENT_FIXTURE,
        lines: [BIGGEST_DISAGREEMENT_FIXTURE.lines[1], BIGGEST_DISAGREEMENT_FIXTURE.lines[2]],
      },
    })
    renderEdge(makeClient())
    await waitFor(() => {
      expect(
        screen.getByText(/Biggest disagreement: Burns, Sam\. The board has him 9 points below the market\./i),
      ).toBeInTheDocument()
    })
  })

  it('picks the largest absolute gap regardless of direction, ignoring synthetic rows', async () => {
    mockFetch({ board: BIGGEST_DISAGREEMENT_FIXTURE })
    renderEdge(makeClient())
    await waitFor(() => {
      // Reitan (+22) beats both Burns (-9) and the synthetic-only Longshot
      // row (-48, but odds_source: 'model' so it must never be considered).
      expect(
        screen.getByText(/Biggest disagreement: Reitan, Kristoffer\. The board has him 22 points above the market\./i),
      ).toBeInTheDocument()
      expect(screen.queryByText(/Synthetic Longshot/i)).not.toBeInTheDocument()
    })
  })

  it('ignores the min-probability filter when finding the biggest disagreement', async () => {
    // Burns has a 5% board probability, below the default >=10% table filter,
    // so he never appears in the chart/table at the default setting. The
    // callout must still be able to name him.
    mockFetch({
      board: {
        ...BIGGEST_DISAGREEMENT_FIXTURE,
        lines: [BIGGEST_DISAGREEMENT_FIXTURE.lines[1], BIGGEST_DISAGREEMENT_FIXTURE.lines[2]],
      },
    })
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Biggest disagreement: Burns, Sam\./i)).toBeInTheDocument()
    })
    // Confirm he's genuinely filtered out of the table at the default threshold.
    expect(screen.queryByRole('cell', { name: 'Burns, Sam' })).not.toBeInTheDocument()
  })

  it('omits the callout when the largest gap is under the 5-point floor', async () => {
    mockFetch({
      board: {
        ...BIGGEST_DISAGREEMENT_FIXTURE,
        lines: [BIGGEST_DISAGREEMENT_FIXTURE.lines[2]], // Small Gap only, -2 points
      },
    })
    renderEdge(makeClient())
    await waitFor(() => expect(screen.getAllByText('Small Gap').length).toBeGreaterThan(0))
    expect(screen.queryByText(/Biggest disagreement/i)).not.toBeInTheDocument()
  })

  it('omits the callout when no line in the market has a real price', async () => {
    mockFetch({ board: ALL_SYNTHETIC_FIXTURE })
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Synthetic odds/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/Biggest disagreement/i)).not.toBeInTheDocument()
  })

  it('breaks a tie on absolute gap by board order', async () => {
    mockFetch({
      board: {
        ...BOARD_FIXTURE,
        lines: [
          { player_id: 1, player_name: 'First Tied', model_prob: 0.3, implied_prob: 0.2, american_odds: 200, edge: 0.1, odds_source: 'datagolf' },
          { player_id: 2, player_name: 'Second Tied', model_prob: 0.1, implied_prob: 0.2, american_odds: 300, edge: -0.1, odds_source: 'datagolf' },
        ],
      },
    })
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Biggest disagreement: First Tied\./i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/Second Tied/i, { selector: 'p' })).not.toBeInTheDocument()
  })

  it('updates the callout when the market picker changes to a different market', async () => {
    mockFetch({
      board: {
        ...BOARD_FIXTURE,
        outcome_key: 'win_prob',
        lines: [
          { player_id: 1, player_name: 'Win Market Leader', model_prob: 0.3, implied_prob: 0.1, american_odds: 200, edge: 0.2, odds_source: 'datagolf' },
        ],
      },
    })
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Biggest disagreement: Win Market Leader\./i)).toBeInTheDocument()
    })

    mockFetch({
      board: {
        ...BOARD_FIXTURE,
        outcome_key: 'make_cut_prob',
        lines: [
          { player_id: 2, player_name: 'Cut Market Leader', model_prob: 0.6, implied_prob: 0.3, american_odds: -150, edge: 0.3, odds_source: 'datagolf' },
        ],
      },
    })
    screen.getByText('Make Cut').click()
    await waitFor(() => {
      expect(screen.getByText(/Biggest disagreement: Cut Market Leader\./i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/Win Market Leader/i)).not.toBeInTheDocument()
  })

  it('does not use betting, edge, or opportunity language in the callout', async () => {
    mockFetch({ board: BIGGEST_DISAGREEMENT_FIXTURE })
    renderEdge(makeClient())
    const callout = await screen.findByText(/Biggest disagreement/i)
    expect(callout.textContent).not.toMatch(/—/)
    expect(callout.textContent).not.toMatch(/edge|bet|opportunity|value|correct|right/i)
  })

  // --- suppression once the event is under way -----------------------------
  // The board is built once, before the event; DataGolf's outrights feed serves
  // current prices. Comparing them mid-event measures the tournament, not a
  // disagreement, so the whole comparison is withheld rather than degraded.
  describe('when the event is under way', () => {
    it('suppresses the callout, the chart, and the table', async () => {
      mockFetch({ tournament: UNDERWAY_TOURNAMENT_FIXTURE })
      renderEdge(makeClient())
      await screen.findByText(/Comparison unavailable once play begins/i)

      expect(screen.queryByText(/Biggest disagreement/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/Largest divergences/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/All priced players/i)).not.toBeInTheDocument()
      expect(screen.queryByText('Rory Birdie')).not.toBeInTheDocument()
    })

    it('hides the market picker and the probability filter', async () => {
      mockFetch({ tournament: UNDERWAY_TOURNAMENT_FIXTURE })
      renderEdge(makeClient())
      await screen.findByText(/Comparison unavailable once play begins/i)

      expect(screen.queryByText('Market')).not.toBeInTheDocument()
      expect(screen.queryByText('Make Cut')).not.toBeInTheDocument()
      expect(screen.queryByText(/Min\. board probability/i)).not.toBeInTheDocument()
    })

    it('keeps the heading and the event name visible', async () => {
      mockFetch({ tournament: UNDERWAY_TOURNAMENT_FIXTURE })
      renderEdge(makeClient())
      await screen.findByText(/Comparison unavailable once play begins/i)

      expect(screen.getByRole('heading', { name: /Market Comparison/i })).toBeInTheDocument()
      expect(screen.getByText(/The Masters/)).toBeInTheDocument()
    })

    it('explains why, without jargon or an em-dash', async () => {
      mockFetch({ tournament: UNDERWAY_TOURNAMENT_FIXTURE })
      renderEdge(makeClient())
      const message = await screen.findByText(/set before the tournament starts/i)

      expect(message.textContent).toMatch(/not updated\s+during play/i)
      expect(message.textContent).toMatch(/move with every shot/i)
      expect(message.textContent).not.toMatch(/—/)
      expect(message.textContent).not.toMatch(/stale|contaminat|in-play|devig/i)
    })

    it('tells the reader when the comparison comes back, without naming an event', async () => {
      mockFetch({ tournament: UNDERWAY_TOURNAMENT_FIXTURE })
      renderEdge(makeClient())
      const line = await screen.findByText(/The comparison returns when the next tournament begins/i)
      expect(line).toBeInTheDocument()
    })

    it('does not request the board it has decided not to show', async () => {
      const fetchMock = mockFetch({ tournament: UNDERWAY_TOURNAMENT_FIXTURE })
      renderEdge(makeClient())
      await screen.findByText(/Comparison unavailable once play begins/i)

      const calls = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(calls.some((u) => u.includes('tournaments/current'))).toBe(true)
      expect(calls.some((u) => u.includes('betting/edge'))).toBe(false)
    })

    it('suppresses on the start date even while the provider still says upcoming', async () => {
      // The calendar backstop alone, with the status signal deliberately stale.
      // This is the half that covers a provider lagging its own status flip.
      mockFetch({
        tournament: { ...TOURNAMENT_FIXTURE, start_date: isoDaysFromNow(0), status: 'upcoming' },
      })
      renderEdge(makeClient())
      await screen.findByText(/Comparison unavailable once play begins/i)
      expect(screen.queryByText(/Biggest disagreement/i)).not.toBeInTheDocument()
    })

    it('suppresses for a completed event', async () => {
      mockFetch({
        tournament: {
          ...TOURNAMENT_FIXTURE,
          start_date: isoDaysFromNow(-6),
          end_date: isoDaysFromNow(-3),
          status: 'completed',
        },
      })
      renderEdge(makeClient())
      await screen.findByText(/Comparison unavailable once play begins/i)
    })
  })

  it('shows the comparison normally for an upcoming event', async () => {
    mockFetch()
    renderEdge(makeClient())
    await waitFor(() => {
      expect(screen.getAllByText('Rory Birdie').length).toBeGreaterThan(0)
    })
    expect(screen.queryByText(/Comparison unavailable once play begins/i)).not.toBeInTheDocument()
    expect(screen.getByText('Market')).toBeInTheDocument()
  })
})
