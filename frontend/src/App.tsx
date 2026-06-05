import { NavLink, Route, Routes } from 'react-router'

import { Home } from './routes/Home'
import { Players } from './routes/Players'
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
          <NavLink to="/players" className={navClass}>
            Players
          </NavLink>
          <NavLink to="/tournaments" className={navClass}>
            Tournaments
          </NavLink>
        </div>
      </nav>

      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/players" element={<Players />} />
        <Route path="/tournaments" element={<Tournaments />} />
      </Routes>
    </div>
  )
}
