import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Tournaments } from './Tournaments'

afterEach(cleanup)

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderTournaments(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <Tournaments />
    </QueryClientProvider>,
  )
}

const TOURNAMENTS_FIXTURE = {
  data: [
    {
      id: 1,
      name: 'The Masters',
      season: 2026,
      start_date: '2026-04-10',
      end_date: '2026-04-13',
      status: 'completed' as const,
      course_id: 1,
      purse: 18_000_000,
      field_strength: null,
    },
    {
      id: 2,
      name: 'The Open',
      season: 2026,
      start_date: '2026-07-10',
      end_date: '2026-07-13',
      status: 'upcoming' as const,
      course_id: 2,
      purse: 15_000_000,
      field_strength: null,
    },
    {
      id: 3,
      name: 'US Open',
      season: 2026,
      start_date: '2026-06-13',
      end_date: '2026-06-16',
      status: 'in_progress' as const,
      course_id: 3,
      purse: 20_000_000,
      field_strength: null,
    },
  ],
  page: { next_cursor: null, has_more: false, total: 3 },
  meta: { as_of: '2026-06-05T00:00:00Z', source: 'mock' },
}

function mockFetch({
  tournaments = TOURNAMENTS_FIXTURE as typeof TOURNAMENTS_FIXTURE | null,
} = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      if (url.includes('/tournaments')) {
        if (tournaments == null) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => tournaments })
      }
      return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
    }),
  )
}

describe('Tournaments', () => {
  it('renders the heading immediately', () => {
    mockFetch()
    renderTournaments(makeClient())
    expect(screen.getByRole('heading', { name: /Tournaments/i })).toBeInTheDocument()
  })

  it('shows tournament names after load', async () => {
    mockFetch()
    renderTournaments(makeClient())
    await waitFor(() => {
      expect(screen.getByText('The Masters')).toBeInTheDocument()
    })
    expect(screen.getByText('The Open')).toBeInTheDocument()
    expect(screen.getByText('US Open')).toBeInTheDocument()
  })

  it('shows tournament status labels', async () => {
    mockFetch()
    renderTournaments(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Completed')).toBeInTheDocument()
    })
    expect(screen.getByText('Upcoming')).toBeInTheDocument()
    expect(screen.getByText('In Progress')).toBeInTheDocument()
  })

  it('shows formatted purse amounts', async () => {
    mockFetch()
    renderTournaments(makeClient())
    await waitFor(() => {
      expect(screen.getByText('$18.0M')).toBeInTheDocument()
    })
    expect(screen.getByText('$20.0M')).toBeInTheDocument()
  })

  it('shows total count from meta', async () => {
    mockFetch()
    renderTournaments(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/3 events/i)).toBeInTheDocument()
    })
  })

  it('shows season year', async () => {
    mockFetch()
    renderTournaments(makeClient())
    await waitFor(() => {
      expect(screen.getAllByText('2026').length).toBeGreaterThan(0)
    })
  })

  it('shows error message on fetch failure', async () => {
    mockFetch({ tournaments: null })
    renderTournaments(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/Error:/i)).toBeInTheDocument()
    })
  })
})
