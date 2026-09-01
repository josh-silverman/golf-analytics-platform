import { Link } from 'react-router'

import { useForwardTrackRecord } from '../lib/api/forwardTrackRecord'
import { orderedSkillMarkets, summarizeTrackRecord } from '../lib/forwardRecord'

const REPO_URL = 'https://github.com/josh-silverman/golf-analytics-platform'

interface FeatureProps {
  to: string
  title: string
  description: string
}

// The primary surface: a wide panel, sized to read as the main entry point
// rather than one of three equal tiles.
function PrimaryFeature({ to, title, description }: FeatureProps) {
  return (
    <Link
      to={to}
      className="group block rounded-xl border border-border-strong bg-surface p-6 transition-colors hover:border-accent-fg/60 sm:p-8"
    >
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="text-xl font-semibold text-fg group-hover:text-accent-fg">{title}</h3>
        <span className="text-sm text-fg-tertiary transition-transform group-hover:translate-x-0.5">
          Open →
        </span>
      </div>
      <p className="mt-2 max-w-xl text-sm leading-relaxed text-fg-secondary">{description}</p>
    </Link>
  )
}

function SecondaryFeature({ to, title, description }: FeatureProps) {
  return (
    <Link
      to={to}
      className="group flex flex-col rounded-xl border bg-surface p-5 transition-colors hover:border-accent-fg/60"
    >
      <h3 className="text-base font-semibold text-fg group-hover:text-accent-fg">{title}</h3>
      <p className="mt-1.5 text-sm leading-relaxed text-fg-tertiary">{description}</p>
    </Link>
  )
}

export function Home() {
  const { data: trackRecord } = useForwardTrackRecord()

  const recordLine =
    trackRecord?.available && trackRecord.markets.length > 0
      ? summarizeTrackRecord(trackRecord, orderedSkillMarkets(trackRecord.markets))
      : null

  return (
    <main className="mx-auto max-w-4xl space-y-14 px-6 py-14 sm:py-20">
      {/* Hero */}
      <header className="max-w-2xl space-y-5">
        <h1 className="text-display font-semibold text-fg">Pinpoint</h1>
        <p className="text-lg leading-snug text-fg sm:text-xl">
          Pre-tournament probabilities for the PGA Tour, graded in the open.
        </p>
        <p className="text-sm leading-relaxed text-fg-secondary">
          Win, top-5, top-10, top-20 and make-cut odds for every player in this week&rsquo;s
          field. Most come straight from DataGolf; an in-house model covers the rest.
        </p>
      </header>

      {/* Live record */}
      <section className="rounded-xl border-l-2 border-accent bg-surface/60 py-4 pl-5 pr-4">
        <p className="text-sm leading-relaxed text-fg-secondary">
          Every board is pinned before the event and scored against the result once it finishes.
          {recordLine ? ` ${recordLine}` : ''}
        </p>
        <Link
          to="/track-record"
          className="mt-2 inline-block text-sm font-medium text-accent-fg hover:underline"
        >
          See the full record →
        </Link>
      </section>

      {/* Surfaces */}
      <section className="space-y-4">
        <PrimaryFeature
          to="/leaderboard"
          title="Prediction Leaderboard"
          description="Win, top-N and make-cut probabilities for any tournament's field. Switch events, sort by market, search the field, and open any player for their strokes-gained trends and current-event outlook."
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <SecondaryFeature
            to="/edge"
            title="Market Comparison"
            description="Board probabilities against book-implied odds for the current field. The disagreement is reported and nothing more is claimed of it. Filter by minimum probability; per-market odds coverage is shown on the page."
          />
          <SecondaryFeature
            to="/track-record"
            title="Track Record"
            description="Past tournaments one week at a time. Every board was pinned before results were known, so nothing here was picked with hindsight."
          />
        </div>
      </section>

      {/* How the record is kept */}
      <section className="space-y-4 border-t pt-10">
        <h2 className="text-base font-semibold text-fg">How the record is kept</h2>
        <ul className="grid gap-x-8 gap-y-3 text-sm leading-relaxed text-fg-secondary sm:grid-cols-2">
          <li>
            Boards are pinned before play begins. The first write for an event wins, and nothing is
            edited afterward.
          </li>
          <li>Results are settled and graded automatically each week.</li>
          <li>
            Predictions recorded live and boards rebuilt afterward are always labeled separately.
          </li>
        </ul>
        <a
          href={REPO_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-block text-sm font-medium text-accent-fg hover:underline"
        >
          Source and full write-up on GitHub →
        </a>
      </section>
    </main>
  )
}
