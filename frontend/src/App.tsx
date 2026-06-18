import { Link, NavLink, Navigate, Route, Routes } from 'react-router'

import { ErrorBoundary } from './components/ErrorBoundary'
import { Home } from './routes/Home'
import { Leaderboard } from './routes/Leaderboard'
import { PlayerDetail } from './routes/PlayerDetail'
import { Players } from './routes/Players'

const navClass = ({ isActive }: { isActive: boolean }) =>
  `text-sm transition-colors ${isActive ? 'text-accent font-medium' : 'text-fg-secondary hover:text-fg'}`

// Views on the roadmap but not yet live. Shown in the nav as disabled "soon"
// chips so the roadmap is legible, and routed to a ComingSoon placeholder so a
// direct URL lands somewhere honest rather than a half-finished page.
const FUTURE = ['Betting Edge', 'Benchmark', 'Diagnostics'] as const

function ComingSoon({ title }: { title: string }) {
  return (
    <main className="mx-auto max-w-6xl px-6 py-20 text-center">
      <p className="text-xs font-medium uppercase tracking-wider text-fg-tertiary">
        Future addition
      </p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mx-auto mt-3 max-w-md text-sm text-fg-secondary">
        This view is on the roadmap and not yet available. The model, leaderboard,
        players, and tournaments are all live today.
      </p>
      <Link to="/leaderboard" className="mt-6 inline-block text-sm text-accent hover:underline">
        → Go to the Leaderboard
      </Link>
    </main>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-background">
      <nav className="border-b bg-surface px-6 py-3">
        <div className="mx-auto flex max-w-6xl items-center gap-6">
          <span className="font-semibold text-fg">PGA Analytics</span>
          <NavLink to="/" end className={navClass}>
            Home
          </NavLink>
          <NavLink to="/leaderboard" className={navClass}>
            Leaderboard
          </NavLink>
          <span className="ml-auto flex items-center gap-4">
            {FUTURE.map((label) => (
              <span
                key={label}
                title="Coming soon"
                className="flex cursor-default items-center gap-1 text-sm text-fg-tertiary/60"
              >
                {label}
                <span className="rounded bg-surface-2 px-1 py-0.5 text-[9px] font-medium uppercase tracking-wide text-fg-tertiary">
                  soon
                </span>
              </span>
            ))}
          </span>
        </div>
      </nav>

      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/leaderboard" element={<ErrorBoundary><Leaderboard /></ErrorBoundary>} />
          <Route path="/players" element={<ErrorBoundary><Players /></ErrorBoundary>} />
          <Route path="/players/:id" element={<ErrorBoundary><PlayerDetail /></ErrorBoundary>} />
          {/* Roadmap views — gated until live. */}
          <Route path="/edge" element={<ComingSoon title="Betting Edge" />} />
          <Route path="/benchmark" element={<ComingSoon title="Benchmark" />} />
          <Route path="/diagnostics" element={<ComingSoon title="Diagnostics" />} />
          {/* Removed (e.g. /tournaments) or unknown paths land on the hub. */}
          <Route path="*" element={<Navigate to="/leaderboard" replace />} />
        </Routes>
      </ErrorBoundary>
    </div>
  )
}
