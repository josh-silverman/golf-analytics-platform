import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { Home } from './Home'

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderHome(client: QueryClient) {
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <Home />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('Home', () => {
  it('renders the page heading immediately', () => {
    renderHome(makeClient())
    expect(screen.getByRole('heading', { name: /Pinpoint/i })).toBeInTheDocument()
  })

  it('links to all four core surfaces', () => {
    renderHome(makeClient())
    expect(screen.getByRole('link', { name: /Prediction Leaderboard/i })).toHaveAttribute(
      'href',
      '/leaderboard',
    )
    expect(screen.getByRole('link', { name: /Market Comparison/i })).toHaveAttribute(
      'href',
      '/edge',
    )
    expect(screen.getByRole('link', { name: /Track Record/i })).toHaveAttribute(
      'href',
      '/track-record',
    )
  })

  // --- unsourced claim removed (audit F3 / H8) ------------------------------
  // "validated skill" named no market, no baseline, no n, no date.

  it('does not assert an unsourced "validated skill" claim', () => {
    renderHome(makeClient())
    expect(screen.queryByText(/validated skill/i)).not.toBeInTheDocument()
  })

  it('does not attribute Betting Edge to "the model" unqualified', () => {
    renderHome(makeClient())
    expect(screen.queryByText(/^Model probabilities/)).not.toBeInTheDocument()
    expect(screen.getByText(/Board probabilities against book-implied odds/i)).toBeInTheDocument()
  })
})
