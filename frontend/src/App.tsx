import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import ChatView from './components/ChatView'
import AdminView from './components/AdminView'

export default function App() {
  const location = useLocation()
  const isChatRoute = location.pathname === '/'

  return (
    <div className={`app-shell ${isChatRoute ? 'chat-locked' : ''}`}>
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
      <main className={`main-content ${isChatRoute ? 'chat-main' : ''}`}>
        <Routes>
          <Route path="/" element={<ChatView />} />
          <Route path="/admin" element={<AdminView />} />
        </Routes>
      </main>
    </div>
  )
}
