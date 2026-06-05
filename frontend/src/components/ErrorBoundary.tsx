/**
 * ErrorBoundary — catches unhandled render errors so a single broken route
 * doesn't white-screen the entire app.
 *
 * React's error boundary API requires a class component; there is no hook
 * equivalent as of React 19.  The boundary renders a minimal fallback card
 * that shows the error message in development and a generic "something went
 * wrong" message in production.
 */

import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Optional custom fallback — replaces the default error card. */
  fallback?: ReactNode
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // In production this is where you'd call Sentry.captureException(error, { extra: info })
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  handleReset = () => {
    this.setState({ error: null })
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback

      const isDev = import.meta.env.DEV

      return (
        <div className="mx-auto max-w-lg px-6 py-16 text-center">
          <p className="text-4xl">⚠️</p>
          <h2 className="mt-4 text-lg font-semibold text-fg">Something went wrong</h2>
          {isDev && (
            <pre className="mt-3 overflow-auto rounded border bg-surface p-4 text-left text-xs text-negative">
              {this.state.error.message}
            </pre>
          )}
          {!isDev && (
            <p className="mt-2 text-sm text-fg-secondary">
              An unexpected error occurred. Try refreshing the page.
            </p>
          )}
          <button
            onClick={this.handleReset}
            className="mt-6 rounded border bg-surface px-4 py-2 text-sm text-fg transition-colors hover:bg-surface-2"
          >
            Try again
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
