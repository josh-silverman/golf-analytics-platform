import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'

import { Benchmark } from './Benchmark'

afterEach(cleanup)

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

const CURRENT_TOURNAMENT = {
  id: 1,
  name: 'The Masters',
  season: 2026,
  start_date: '2026-04-10',
  end_date: '2026-04-13',
  status: 'in_progress' as const,
  course_id: 1,
  purse: 18_000_000,
  field_strength: null,
}

const BENCHMARK_MOCK = {
  tournament_id: 1,
  tournament_name: 'The Masters',
  model_name: 'golf_v1',
  model_version_id: 'abc12345',
  dg_available: false,
  dg_last_updated: null,
  rows: [
    {
      player_id: 101,
      player_name: 'Rory McIlroy',
      our_win_prob: 0.12,
      our_top_10_prob: 0.55,
      our_make_cut_prob: 0.9,
      dg_win_prob: null,
      dg_top_10_prob: null,
      dg_make_cut_prob: null,
      win_diff: null,
    },
    {
      player_id: 102,
      player_name: 'Scottie Scheffler',
      our_win_prob: 0.18,
      our_top_10_prob: 0.65,
      our_make_cut_prob: 0.95,
      dg_win_prob: null,
      dg_top_10_prob: null,
      dg_make_cut_prob: null,
      win_diff: null,
    },
  ],
}

const BENCHMARK_DG = {
  ...BENCHMARK_MOCK,
  dg_available: true,
  dg_last_updated: '2026-04-10 08:00:00',
  rows: BENCHMARK_MOCK.rows.map((r, i) => ({
    ...r,
    dg_win_prob: i === 0 ? 0.10 : 0.20,
    dg_top_10_prob: i === 0 ? 0.50 : 0.70,
    dg_make_cut_prob: i === 0 ? 0.88 : 0.96,
    win_diff: i === 0 ? 0.02 : -0.02,
  })),
}

function mockFetch(benchmark: typeof BENCHMARK_MOCK = BENCHMARK_MOCK) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      if (url.includes('/tournaments/current')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ data: CURRENT_TOURNAMENT }),
        })
      }
      if (url.includes('/analytics/benchmark')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => benchmark })
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
    }),
  )
}

function renderBenchmark(client: QueryClient) {
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <Benchmark />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('Benchmark', () => {
  it('renders the heading', () => {
    mockFetch()
    renderBenchmark(makeClient())
    expect(screen.getByRole('heading', { name: /Model Benchmark/i })).toBeInTheDocument()
  })

  it('shows the tournament name after load', async () => {
    mockFetch()
    renderBenchmark(makeClient())
    await waitFor(() => {
      expect(screen.getByText('The Masters')).toBeInTheDocument()
    })
  })

  it('shows player rows in the table', async () => {
    mockFetch()
    renderBenchmark(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Rory McIlroy')).toBeInTheDocument()
    })
    expect(screen.getByText('Scottie Scheffler')).toBeInTheDocument()
  })

  it('shows the DataGolf callout when dg_available is false', async () => {
    mockFetch()
    renderBenchmark(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/DataGolf API not connected/i)).toBeInTheDocument()
    })
  })

  it('shows DG columns and diff badges when dg_available is true', async () => {
    mockFetch(BENCHMARK_DG)
    renderBenchmark(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Rory McIlroy')).toBeInTheDocument()
    })
    // Diff column header should appear
    expect(screen.getByText('Diff')).toBeInTheDocument()
    // +2.0pp diff badge
    expect(screen.getByText('+2.0pp')).toBeInTheDocument()
  })

  it('shows our win probability formatted', async () => {
    mockFetch()
    renderBenchmark(makeClient())
    await waitFor(() => {
      expect(screen.getByText('12.0%')).toBeInTheDocument()
    })
  })
})
