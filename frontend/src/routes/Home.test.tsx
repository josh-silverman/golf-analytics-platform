import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Home } from './Home'

function renderWithProviders() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <Home />
    </QueryClientProvider>,
  )
}

describe('Home', () => {
  it('renders the page heading immediately', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: 'ok' }),
      }),
    )

    renderWithProviders()

    expect(
      screen.getByRole('heading', { name: /PGA Tour Analytics/i }),
    ).toBeInTheDocument()
  })

  it('renders the healthz status when the backend responds', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: 'ok' }),
      }),
    )

    renderWithProviders()

    await waitFor(() => {
      expect(screen.getByText('ok')).toBeInTheDocument()
    })
  })

  it('renders an error message when the backend fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
      }),
    )

    renderWithProviders()

    await waitFor(() => {
      expect(screen.getByText(/Error:/i)).toBeInTheDocument()
    })
  })
})
