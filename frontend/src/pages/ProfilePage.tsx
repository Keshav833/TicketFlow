import { LogOut, Mail, UserRound } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'

export function ProfilePage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const signOut = () => {
    logout()
    navigate('/')
  }

  if (!user) return null

  return (
    <div className="content-wrap page-section narrow-page">
      <div className="page-heading">
        <p className="eyebrow">YOUR ACCOUNT</p>
        <h1>Profile</h1>
        <p>Your TicketFlow account details.</p>
      </div>
      <section className="profile-card">
        <span className="profile-avatar"><UserRound size={27} /></span>
        <div className="profile-row"><span>Username</span><strong>{user.username}</strong></div>
        <div className="profile-row"><span><Mail size={15} /> Email address</span><strong>{user.email || 'Not provided'}</strong></div>
        <p className="ticket-note">Profile editing is not supported by the current account API.</p>
        <button className="button button-secondary" onClick={signOut}><LogOut size={16} /> Sign out</button>
      </section>
    </div>
  )
}
