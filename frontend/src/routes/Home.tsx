import { Link } from 'react-router'

import { useHealthz } from '../lib/api/health'
import { useCurrentTournament } from '../lib/api/tournaments'

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

export function Home() {
  const { data: health, isLoading: healthLoading, isError: healthError } = useHealthz()
  const { data: currentTournament, isLoading: tournamentLoading } = useCurrentTournament()

  return (
    <main className="mx-auto max-w-4xl space-y-8 px-6 py-12">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">PGA Tour Analytics</h1>
        <p className="mt-2 text-fg-secondary">
          ML-driven tournament analysis and field strength modeling
        </p>
      </header>

      <section className="rounded-lg border bg-surface p-6">
        <h2 className="mb-3 text-xs uppercase tracking-wider text-fg-tertiary">
          Current Event
        </h2>
        {tournamentLoading && <p className="text-fg-secondary">Loading…</p>}
        {currentTournament && (
          <div>
            <p className="text-lg font-medium text-fg">{currentTournament.name}</p>
            <p className="mt-1 text-sm text-fg-secondary">
              {formatDate(currentTournament.start_date)} – {formatDate(currentTournament.end_date)}
            </p>
            <p className="mt-1 text-xs font-medium capitalize text-accent">
              {currentTournament.status.replace('_', ' ')}
            </p>
          </div>
        )}
        {!tournamentLoading && currentTournament === null && (
          <p className="text-fg-secondary">No active tournament</p>
        )}
      </section>

      <div className="grid grid-cols-2 gap-4">
        <Link
          to="/players"
          className="rounded-lg border bg-surface p-5 transition-colors hover:border-accent"
        >
          <p className="text-xs uppercase tracking-wider text-fg-tertiary">Browse</p>
          <p className="mt-1 text-lg font-medium text-fg">Players</p>
        </Link>
        <Link
          to="/tournaments"
          className="rounded-lg border bg-surface p-5 transition-colors hover:border-accent"
        >
          <p className="text-xs uppercase tracking-wider text-fg-tertiary">Browse</p>
          <p className="mt-1 text-lg font-medium text-fg">Tournaments</p>
        </Link>
      </div>

      <section className="rounded-lg border bg-surface p-6">
        <h2 className="mb-3 text-xs uppercase tracking-wider text-fg-tertiary">
          Backend /healthz
        </h2>
        {healthLoading && <p className="text-fg-secondary">Checking…</p>}
        {healthError && <p className="text-negative">Backend unreachable</p>}
        {health && (
          <p className="font-mono tabular-nums">
            <span className="text-positive">●</span>{' '}
            <span className="text-fg-secondary">status:</span>{' '}
            <span className="text-fg">{health.status}</span>
          </p>
        )}
      </section>
    </main>
  )
}
