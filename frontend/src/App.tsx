import { NavLink, Navigate, Route, Routes } from 'react-router'

import { ErrorBoundary } from './components/ErrorBoundary'
import { BettingEdge } from './routes/BettingEdge'
import { Home } from './routes/Home'
import { Leaderboard } from './routes/Leaderboard'
import { PlayerDetail } from './routes/PlayerDetail'
import { Players } from './routes/Players'

const navClass = ({ isActive }: { isActive: boolean }) =>
  `text-sm transition-colors ${isActive ? 'text-accent font-medium' : 'text-fg-secondary hover:text-fg'}`

export default function App() {
  return (
    <div className="min-h-screen bg-background">
      <nav className="border-b bg-surface px-6 py-3">
        <div className="mx-auto flex max-w-6xl items-center gap-6">
          <span className="font-semibold text-fg">Pinpoint Analytics</span>
          <NavLink to="/" end className={navClass}>
            Home
          </NavLink>
          <NavLink to="/leaderboard" className={navClass}>
            Leaderboard
          </NavLink>
          <NavLink to="/edge" className={navClass}>
            Betting Edge
          </NavLink>
        </div>
      </nav>

      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/leaderboard" element={<ErrorBoundary><Leaderboard /></ErrorBoundary>} />
          <Route path="/players" element={<ErrorBoundary><Players /></ErrorBoundary>} />
          <Route path="/players/:id" element={<ErrorBoundary><PlayerDetail /></ErrorBoundary>} />
          <Route path="/edge" element={<ErrorBoundary><BettingEdge /></ErrorBoundary>} />
          {/* Removed (e.g. /tournaments) or unknown paths land on the hub. */}
          <Route path="*" element={<Navigate to="/leaderboard" replace />} />
        </Routes>
      </ErrorBoundary>
    </div>
  )
}
