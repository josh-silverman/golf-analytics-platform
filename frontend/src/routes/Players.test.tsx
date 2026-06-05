import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Players } from './Players'

afterEach(cleanup)

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderPlayers(client: QueryClient) {
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <Players />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

const PLAYERS_FIXTURE = {
  data: [
    { id: 1, dg_id: 1001, full_name: 'Rory Birdie', country: 'IRL', dob: null, turned_pro: 2004 },
    { id: 2, dg_id: 1002, full_name: 'Tiger Chip', country: 'USA', dob: null, turned_pro: 1996 },
  ],
  page: { next_cursor: null, has_more: false, total: 2 },
  meta: { as_of: '2026-06-01T00:00:00Z', source: 'mock' },
}

function mockFetch({
  players = PLAYERS_FIXTURE as typeof PLAYERS_FIXTURE | null,
} = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      if (url.includes('/players')) {
        if (players == null) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => players })
      }
      return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
    }),
  )
}

describe('Players', () => {
  it('renders the heading immediately', () => {
    mockFetch()
    renderPlayers(makeClient())
    expect(screen.getByRole('heading', { name: /Players/i })).toBeInTheDocument()
  })

  it('shows player names after load', async () => {
    mockFetch()
    renderPlayers(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Rory Birdie')).toBeInTheDocument()
    })
    expect(screen.getByText('Tiger Chip')).toBeInTheDocument()
  })

  it('shows country codes', async () => {
    mockFetch()
    renderPlayers(makeClient())
    await waitFor(() => {
      expect(screen.getByText('IRL')).toBeInTheDocument()
    })
    expect(screen.getByText('USA')).toBeInTheDocument()
  })

  it('shows turned-pro year', async () => {
    mockFetch()
    renderPlayers(makeClient())
    await waitFor(() => {
      expect(screen.getByText('2004')).toBeInTheDocument()
    })
  })

  it('shows total player count from meta', async () => {
    mockFetch()
    renderPlayers(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/2 players/i)).toBeInTheDocument()
    })
  })

  it('player names are links to detail pages', async () => {
    mockFetch()
    renderPlayers(makeClient())
    await waitFor(() => {
      const link = screen.getByRole('link', { name: 'Rory Birdie' })
      expect(link).toHaveAttribute('href', '/players/1')
    })
  })

  it('shows error message on fetch failure', async () => {
    mockFetch({ players: null })
    renderPlayers(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Error:/i)).toBeInTheDocument()
    })
  })
})
