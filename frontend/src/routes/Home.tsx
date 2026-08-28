import { Link } from 'react-router'

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

export function Home() {
  return (
    <main className="mx-auto max-w-4xl space-y-8 px-6 py-12">
      {/* ------------------------------------------------------------------ */}
      {/* Hero                                                                */}
      {/* ------------------------------------------------------------------ */}
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Pinpoint</h1>
        <p className="text-xs uppercase tracking-[0.25em] text-fg-tertiary">Golf Analytics</p>
        <p className="max-w-xl text-fg-secondary">
          Calibrated win / top-5 / top-10 / top-20 / make-cut probabilities for the full field
          of the current PGA Tour event. Most players are priced directly from DataGolf; an
          in-house model fills the players DataGolf doesn&rsquo;t cover. Every week&rsquo;s
          predictions are graded publicly against what actually happened.
        </p>
      </header>

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
          <FeatureCard
            to="/edge"
            category="Research"
            title="Market Comparison"
            description="Where the served board diverges from the market — board probabilities vs. book-implied odds for the current event. The disagreement is reported and nothing more is claimed of it. Filter by minimum probability; per-market odds coverage is shown on the page."
          />
          <FeatureCard
            to="/track-record"
            category="History"
            title="Track Record"
            description="Browse past tournaments one week at a time and see how that week's predictions performed against the field. Pinned before results were known; nothing here is graded after the fact."
          />
        </div>
      </section>
    </main>
  )
}
