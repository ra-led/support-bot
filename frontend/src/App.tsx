import { NavLink, Route, Routes } from 'react-router-dom'
import ChatView from './components/ChatView'
import AdminView from './components/AdminView'

export default function App() {
  return (
    <div className="app-shell">
      <header className="navbar nes-container">
        <div className="header-title">
          <strong>Facility Intake Bot</strong>
        </div>
        <nav className="nav-links">
          <NavLink to="/" className="nes-btn is-primary">
            Chat
          </NavLink>
          <NavLink to="/admin" className="nes-btn is-primary">
            Admin
          </NavLink>
        </nav>
      </header>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<ChatView />} />
          <Route path="/admin" element={<AdminView />} />
        </Routes>
      </main>
    </div>
  )
}
