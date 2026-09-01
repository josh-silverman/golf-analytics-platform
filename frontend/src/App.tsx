import { NavLink, Navigate, Route, Routes } from 'react-router'

import { ErrorBoundary } from './components/ErrorBoundary'
import { BettingEdge } from './routes/BettingEdge'
import { Home } from './routes/Home'
import { Leaderboard } from './routes/Leaderboard'
import { PlayerDetail } from './routes/PlayerDetail'
import { TrackRecord } from './routes/TrackRecord'

const navClass = ({ isActive }: { isActive: boolean }) =>
  `shrink-0 text-sm transition-colors ${
    isActive ? 'text-accent-fg font-medium' : 'text-fg-secondary hover:text-fg'
  }`

// Brand mark: a crosshair, matching the favicon. A single geometric figure,
// not a decorative illustration.
function Wordmark() {
  return (
    <NavLink to="/" end className="flex items-center gap-2">
      <svg width="18" height="18" viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
        <circle cx="16" cy="16" r="8" fill="none" stroke="#34A65F" strokeWidth="2.5" />
        <circle cx="16" cy="16" r="2.6" fill="#34A65F" />
        <path
          d="M16 2v6M16 24v6M2 16h6M24 16h6"
          stroke="#34A65F"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
      <span className="font-semibold tracking-tight text-fg">Pinpoint</span>
    </NavLink>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-background">
      <nav className="sticky top-0 z-40 border-b border-border/80 bg-background/80 px-6 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 sm:gap-6">
          <Wordmark />
          {/* On narrow screens the link strip scrolls rather than wrapping to a
              second row or collapsing to a menu. */}
          <div className="flex items-center gap-5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <NavLink to="/" end className={navClass}>
              Home
            </NavLink>
            <NavLink to="/leaderboard" className={navClass}>
              Leaderboard
            </NavLink>
            <NavLink to="/edge" className={navClass}>
              Market Comparison
            </NavLink>
            <NavLink to="/track-record" className={navClass}>
              Track Record
            </NavLink>
          </div>
        </div>
      </nav>

      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/leaderboard" element={<ErrorBoundary><Leaderboard /></ErrorBoundary>} />
          <Route path="/players/:id" element={<ErrorBoundary><PlayerDetail /></ErrorBoundary>} />
          <Route path="/edge" element={<ErrorBoundary><BettingEdge /></ErrorBoundary>} />
          <Route path="/track-record" element={<ErrorBoundary><TrackRecord /></ErrorBoundary>} />
          {/* Removed (e.g. /tournaments) or unknown paths land on the hub. */}
          <Route path="*" element={<Navigate to="/leaderboard" replace />} />
        </Routes>
      </ErrorBoundary>
    </div>
  )
}
