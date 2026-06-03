import { Route, Routes } from 'react-router'

import { Home } from './routes/Home'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
    </Routes>
  )
}
