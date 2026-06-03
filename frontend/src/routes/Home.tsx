import { useHealthz } from '../lib/api/health'

export function Home() {
  const { data, isLoading, isError, error } = useHealthz()

  return (
    <main className="min-h-screen bg-background text-fg">
      <div className="mx-auto max-w-4xl space-y-8 px-6 py-12">
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">PGA Tour Analytics</h1>
          <p className="mt-2 text-fg-secondary">
            Phase 0 — backend connectivity check
          </p>
        </header>

        <section className="rounded-lg border bg-surface p-6">
          <h2 className="mb-3 text-xs uppercase tracking-wider text-fg-tertiary">
            Backend /healthz
          </h2>

          {isLoading && <p className="text-fg-secondary">Checking…</p>}

          {isError && (
            <p className="text-negative">
              Error: {error instanceof Error ? error.message : 'Unknown failure'}
            </p>
          )}

          {data && (
            <p className="font-mono tabular-nums">
              <span className="text-positive">●</span>{' '}
              <span className="text-fg-secondary">status:</span>{' '}
              <span className="text-fg">{data.status}</span>
            </p>
          )}
        </section>
      </div>
    </main>
  )
}
