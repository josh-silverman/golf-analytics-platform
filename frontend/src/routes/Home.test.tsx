import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

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

const TOURNAMENT_FIXTURE = {
  id: 1,
  name: 'The Masters',
  season: 2026,
  start_date: '2026-04-10',
  end_date: '2026-04-13',
  status: 'in_progress',
  course_id: 1,
  purse: 20_000_000,
  field_strength: null,
}

function mockFetch({
  health = true,
  tournament = TOURNAMENT_FIXTURE as typeof TOURNAMENT_FIXTURE | null,
}: { health?: boolean; tournament?: typeof TOURNAMENT_FIXTURE | null } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      if ((url as string).includes('tournaments/current')) {
        if (tournament == null) {
          return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ data: tournament }),
        })
      }
      if (health) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ status: 'ok' }) })
      }
      return Promise.resolve({ ok: false, status: 503, json: async () => ({}) })
    }),
  )
}

describe('Home', () => {
  it('renders the page heading immediately', () => {
    mockFetch()
    renderHome(makeClient())
    expect(screen.getByRole('heading', { name: /Pinpoint/i })).toBeInTheDocument()
  })

  it('renders the healthz status when the backend responds', async () => {
    mockFetch()
    renderHome(makeClient())
    await waitFor(() => {
      expect(screen.getByText('ok')).toBeInTheDocument()
    })
  })

  it('shows current tournament name when API returns one', async () => {
    mockFetch()
    renderHome(makeClient())
    await waitFor(() => {
      expect(screen.getByText('The Masters')).toBeInTheDocument()
    })
  })

  it('shows "No active tournament" when current endpoint returns 404', async () => {
    mockFetch({ tournament: null })
    renderHome(makeClient())
    await waitFor(() => {
      expect(screen.getByText('No active tournament')).toBeInTheDocument()
    })
  })

  it('renders an error indicator when the backend health check fails', async () => {
    mockFetch({ health: false, tournament: null })
    renderHome(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Backend unreachable')).toBeInTheDocument()
    })
  })
})
