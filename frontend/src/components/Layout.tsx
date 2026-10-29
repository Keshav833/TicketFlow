import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Menu, Ticket, X } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'

export function Layout() {
  const { user, logout, expired, clearExpired } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const navigate = useNavigate()

  const closeMenu = () => setMenuOpen(false)
  const onLogout = () => {
    logout()
    closeMenu()
    navigate('/')
  }

  return (
    <div className="site-shell">
      <header className="site-header">
        <div className="header-inner">
          <Link to="/" className="brand" onClick={closeMenu} aria-label="TicketFlow home">
            <span className="brand-icon"><Ticket size={19} strokeWidth={2.2} /></span>
            <span>ticketflow<span className="brand-period">.</span></span>
          </Link>
          <button
            type="button"
            className="mobile-menu-toggle"
            aria-label={menuOpen ? 'Close navigation' : 'Open navigation'}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <X size={21} /> : <Menu size={21} />}
          </button>
          <nav className={`main-nav ${menuOpen ? 'nav-open' : ''}`} aria-label="Main navigation">
            <NavLink to="/events" onClick={closeMenu}>Discover events</NavLink>
            {user ? (
              <>
                <NavLink to="/my-bookings" onClick={closeMenu}>My bookings</NavLink>
                <NavLink to="/profile" onClick={closeMenu}>Profile</NavLink>
                <button className="nav-action" onClick={onLogout}>Sign out</button>
              </>
            ) : (
              <>
                <NavLink to="/login" onClick={closeMenu}>Sign in</NavLink>
                <Link to="/register" className="button button-primary nav-cta" onClick={closeMenu}>
                  Create account
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>
      {expired && (
        <div className="session-notice" role="status">
          Your session expired. Sign in again to continue.
          <button type="button" onClick={clearExpired} aria-label="Dismiss session notice">Dismiss</button>
        </div>
      )}
      <main className="main-content"><Outlet /></main>
      <footer className="site-footer">
        <div className="footer-inner">
          <Link to="/" className="brand footer-brand">
            <span className="brand-icon"><Ticket size={18} /></span>
            <span>ticketflow<span className="brand-period">.</span></span>
          </Link>
          <p>Make room for a good time.</p>
          <div className="footer-links">
            <Link to="/events">Explore events</Link>
            {user && <Link to="/my-bookings">My bookings</Link>}
          </div>
          <span className="footer-copy">© {new Date().getFullYear()} TicketFlow</span>
        </div>
      </footer>
    </div>
  )
}
