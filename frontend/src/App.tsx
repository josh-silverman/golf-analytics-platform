import { NavLink, Route, Routes } from 'react-router'

import { ErrorBoundary } from './components/ErrorBoundary'
import { Benchmark } from './routes/Benchmark'
import { BettingEdge } from './routes/BettingEdge'
import { Diagnostics } from './routes/Diagnostics'
import { Home } from './routes/Home'
import { Leaderboard } from './routes/Leaderboard'
import { PlayerDetail } from './routes/PlayerDetail'
import { Players } from './routes/Players'
import { Simulations } from './routes/Simulations'
import { TournamentDetail } from './routes/TournamentDetail'
import { Tournaments } from './routes/Tournaments'

const navClass = ({ isActive }: { isActive: boolean }) =>
  `text-sm transition-colors ${isActive ? 'text-accent font-medium' : 'text-fg-secondary hover:text-fg'}`

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
          <NavLink to="/players" className={navClass}>
            Players
          </NavLink>
          <NavLink to="/tournaments" className={navClass}>
            Tournaments
          </NavLink>
          <NavLink to="/simulations" className={navClass}>
            Simulation
          </NavLink>
          <NavLink to="/edge" className={navClass}>
            Betting Edge
          </NavLink>
          <NavLink to="/benchmark" className={navClass}>
            Benchmark
          </NavLink>
          <NavLink to="/diagnostics" className={navClass}>
            Diagnostics
          </NavLink>
        </div>
      </nav>

      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/leaderboard" element={<ErrorBoundary><Leaderboard /></ErrorBoundary>} />
          <Route path="/simulations" element={<ErrorBoundary><Simulations /></ErrorBoundary>} />
          <Route path="/edge" element={<ErrorBoundary><BettingEdge /></ErrorBoundary>} />
          <Route path="/players" element={<ErrorBoundary><Players /></ErrorBoundary>} />
          <Route path="/players/:id" element={<ErrorBoundary><PlayerDetail /></ErrorBoundary>} />
          <Route path="/tournaments" element={<ErrorBoundary><Tournaments /></ErrorBoundary>} />
          <Route path="/tournaments/:id" element={<ErrorBoundary><TournamentDetail /></ErrorBoundary>} />
          <Route path="/benchmark" element={<ErrorBoundary><Benchmark /></ErrorBoundary>} />
          <Route path="/diagnostics" element={<ErrorBoundary><Diagnostics /></ErrorBoundary>} />
        </Routes>
      </ErrorBoundary>
    </div>
  )
}
