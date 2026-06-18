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

interface FeatureCardProps {
  to: string
  category: string
  title: string
  description: string
  badge?: string
}

function FeatureCard({ to, category, title, description, badge }: FeatureCardProps) {
  return (
    <Link
      to={to}
      className="group flex flex-col rounded-lg border bg-surface p-5 transition-colors hover:border-accent"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs uppercase tracking-wider text-fg-tertiary">{category}</p>
        {badge && (
          <span className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-semibold text-accent">
            {badge}
          </span>
        )}
      </div>
      <p className="mt-1 text-base font-medium text-fg group-hover:text-accent">{title}</p>
      <p className="mt-1 text-xs text-fg-tertiary">{description}</p>
    </Link>
  )
}

interface PillProps {
  label: string
}

function Pill({ label }: PillProps) {
  return (
    <span className="rounded border bg-surface px-2 py-0.5 font-mono text-[11px] text-fg-secondary">
      {label}
    </span>
  )
}

export function Home() {
  const { data: health, isLoading: healthLoading, isError: healthError } = useHealthz()
  const { data: currentTournament, isLoading: tournamentLoading } = useCurrentTournament()

  return (
    <main className="mx-auto max-w-4xl space-y-8 px-6 py-12">
      {/* ------------------------------------------------------------------ */}
      {/* Hero                                                                */}
      {/* ------------------------------------------------------------------ */}
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">PGA Tour Analytics</h1>
        <p className="max-w-xl text-fg-secondary">
          End-to-end sports analytics platform: strokes-gained feature engineering,
          gradient-boosted outcome classification, and per-market probability
          calibration — all on live tour data.
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          <Pill label="FastAPI" />
          <Pill label="scikit-learn" />
          <Pill label="numpy" />
          <Pill label="React" />
          <Pill label="TanStack Query" />
          <Pill label="Tailwind" />
          <Pill label="Fly.io + Vercel" />
        </div>
      </header>

      {/* ------------------------------------------------------------------ */}
      {/* Current tournament                                                  */}
      {/* ------------------------------------------------------------------ */}
      <section className="rounded-lg border bg-surface p-5">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-fg-tertiary">
          Current Event
        </p>
        {tournamentLoading && <p className="text-fg-secondary text-sm">Loading…</p>}
        {currentTournament && (
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-base font-medium text-fg">{currentTournament.name}</p>
              <p className="mt-0.5 text-sm text-fg-secondary">
                {formatDate(currentTournament.start_date)} –{' '}
                {formatDate(currentTournament.end_date)}
              </p>
              {currentTournament.purse && (
                <p className="mt-0.5 text-xs text-fg-tertiary">
                  Purse: ${(currentTournament.purse / 1_000_000).toFixed(1)}M
                </p>
              )}
            </div>
            <span className="shrink-0 rounded-full bg-accent/10 px-2.5 py-1 text-xs font-semibold capitalize text-accent">
              {currentTournament.status.replace('_', ' ')}
            </span>
          </div>
        )}
        {!tournamentLoading && currentTournament == null && (
          <p className="text-sm text-fg-secondary">No active tournament</p>
        )}
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Feature grid                                                        */}
      {/* ------------------------------------------------------------------ */}
      <section className="space-y-3">
        <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">Features</p>
        <div className="grid grid-cols-1 gap-3">
          <FeatureCard
            to="/leaderboard"
            category="Predictions"
            title="Prediction Leaderboard"
            description="Win / top-N / make-cut probabilities for any tournament's field. Switch events, sort by market, search players, and click any name for their strokes-gained trends and current-event outlook."
          />
        </div>
        <p className="text-xs text-fg-tertiary">
          <span className="font-medium text-fg-secondary">Model reliability</span> · out-of-sample
          Brier skill (higher = more reliable):{' '}
          <span className="font-mono text-accent">Make cut +0.16</span> ·{' '}
          <span className="font-mono text-accent">Top 20 +0.07</span> ·{' '}
          <span className="font-mono">Top 10 +0.05</span> ·{' '}
          <span className="font-mono">Top 5 +0.05</span> ·{' '}
          <span className="font-mono text-fg-tertiary">Win +0.00</span>
        </p>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Backend health                                                      */}
      {/* ------------------------------------------------------------------ */}
      <section className="flex items-center justify-between rounded-lg border bg-surface px-5 py-3">
        <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">
          Backend health
        </p>
        {healthLoading && <p className="text-xs text-fg-secondary">Checking…</p>}
        {healthError && (
          <p className="text-xs font-mono text-negative">Backend unreachable</p>
        )}
        {health && (
          <p className="font-mono text-xs">
            <span className="text-positive">●</span>{' '}
            <span className="text-fg">{health.status}</span>
          </p>
        )}
      </section>
    </main>
  )
}
