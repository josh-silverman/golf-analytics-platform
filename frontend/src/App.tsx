import { NavLink, Route, Routes } from 'react-router'

import { BettingEdge } from './routes/BettingEdge'
import { Diagnostics } from './routes/Diagnostics'
import { Home } from './routes/Home'
import { Leaderboard } from './routes/Leaderboard'
import { PlayerDetail } from './routes/PlayerDetail'
import { Players } from './routes/Players'
import { Simulations } from './routes/Simulations'
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
          <NavLink to="/diagnostics" className={navClass}>
            Diagnostics
          </NavLink>
        </div>
      </nav>

      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/leaderboard" element={<Leaderboard />} />
        <Route path="/simulations" element={<Simulations />} />
        <Route path="/edge" element={<BettingEdge />} />
        <Route path="/players" element={<Players />} />
        <Route path="/players/:id" element={<PlayerDetail />} />
        <Route path="/tournaments" element={<Tournaments />} />
        <Route path="/diagnostics" element={<Diagnostics />} />
      </Routes>
    </div>
  )
}
