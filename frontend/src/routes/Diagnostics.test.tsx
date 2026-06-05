import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Diagnostics } from './Diagnostics'

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderDiagnostics(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <Diagnostics />
    </QueryClientProvider>,
  )
}

const REPORT_FIXTURE = {
  model_name: 'golf_v1',
  model_version_id: 'abc123def456',
  n_calibration_examples: 200,
  outcomes: [
    {
      outcome_key: 'win_prob',
      brier_raw: 0.052,
      brier_calibrated: 0.041,
      bins_raw: [
        { lower: 0, upper: 0.1, mean_predicted: 0.05, observed_frequency: 0.04, count: 120 },
      ],
      bins_calibrated: [
        { lower: 0, upper: 0.1, mean_predicted: 0.05, observed_frequency: 0.048, count: 120 },
      ],
    },
  ],
}

function mockFetch(response: { status: number; body?: unknown }) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: response.status >= 200 && response.status < 300,
        status: response.status,
        json: async () => response.body ?? {},
      }),
    ),
  )
}

describe('Diagnostics', () => {
  it('renders the heading immediately', () => {
    mockFetch({ status: 200, body: REPORT_FIXTURE })
    renderDiagnostics(makeClient())
    expect(screen.getByRole('heading', { name: /ML Diagnostics/i })).toBeInTheDocument()
  })

  it('renders an outcome card with calibrated Brier when the report loads', async () => {
    mockFetch({ status: 200, body: REPORT_FIXTURE })
    renderDiagnostics(makeClient())
    await waitFor(() => {
      expect(screen.getByText('Win')).toBeInTheDocument()
    })
    expect(screen.getByText('0.0410')).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: /Reliability diagram for Win/i }),
    ).toBeInTheDocument()
  })

  it('shows a no-model message on 404', async () => {
    mockFetch({ status: 404 })
    renderDiagnostics(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/No trained model is registered/i)).toBeInTheDocument()
    })
  })

  it('shows an uncalibrated message on 409', async () => {
    mockFetch({ status: 409 })
    renderDiagnostics(makeClient())
    await waitFor(() => {
      expect(screen.getByText(/has no calibration data/i)).toBeInTheDocument()
    })
  })
})
