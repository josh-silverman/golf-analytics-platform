import * as Sentry from '@sentry/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import App from './App'
import './index.css'

// Sentry is only initialised when VITE_SENTRY_DSN is set at build time.
// In development and CI it remains a no-op — no DSN = no network calls.
const sentryDsn = import.meta.env.VITE_SENTRY_DSN as string | undefined

if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    environment: import.meta.env.MODE,
    // Capture 10 % of page loads for performance tracing.
    tracesSampleRate: 0.1,
    // Only send errors from our own origin, not injected third-party scripts.
    allowUrls: [window.location.origin],
  })
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
})

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Could not find root element to mount the React app.')
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
