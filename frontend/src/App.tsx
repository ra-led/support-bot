import { NavLink, Route, Routes } from 'react-router-dom'
import ChatView from './components/ChatView'
import AdminView from './components/AdminView'

export default function App() {
  return (
    <div className="app-shell">
      <header className="navbar">
        <div className="header-title">
          <strong>Facility Intake Assistant</strong>
        </div>
        <nav className="nav-links">
          <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            Chat
          </NavLink>
          <NavLink
            to="/admin"
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          >
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
