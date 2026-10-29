import { Eye, EyeOff, Ticket } from 'lucide-react'
import { FormEvent, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { getApiErrorMessage } from '../api/client'

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const isRegister = mode === 'register'
  const { login, register, clearExpired } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [registered, setRegistered] = useState(Boolean(location.state?.registered))

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      if (isRegister) {
        await register({ username: username.trim(), email: email.trim(), password })
        setRegistered(true)
        setPassword('')
        return
      }
      await login(username.trim(), password)
      clearExpired()
      const returnTo = location.state?.from?.pathname || '/'
      navigate(returnTo, { replace: true })
    } catch (cause) {
      setError(getApiErrorMessage(cause))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page content-wrap">
      <section className="auth-card">
        <div className="auth-mark"><Ticket size={21} /></div>
        <p className="eyebrow">{isRegister ? 'JOIN THE GOOD TIMES' : 'WELCOME BACK'}</p>
        <h1>{isRegister ? 'Create your account' : 'Sign in to TicketFlow'}</h1>
        <p className="auth-intro">
          {isRegister ? 'A few details and you’re ready to make plans.' : 'Your next great experience is just around the corner.'}
        </p>
        {registered && isRegister ? (
          <div className="success-message" role="status">
            Your account is ready. Sign in to start booking.
            <Link to="/login" state={{ registered: true }}>Go to sign in</Link>
          </div>
        ) : (
          <form className="auth-form" onSubmit={submit}>
            <label htmlFor="username">Username</label>
            <input
              id="username"
              name="username"
              autoComplete="username"
              required
              minLength={1}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="Your username"
            />
            {isRegister && (
              <>
                <label htmlFor="email">Email address</label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                />
              </>
            )}
            <label htmlFor="password">Password</label>
            <div className="password-field">
              <input
                id="password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete={isRegister ? 'new-password' : 'current-password'}
                required
                minLength={isRegister ? 8 : 1}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={isRegister ? 'At least 8 characters' : 'Your password'}
              />
              <button
                type="button"
                className="password-toggle"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword((value) => !value)}
              >
                {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button type="submit" className="button button-primary button-full" disabled={submitting}>
              {submitting ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in'}
            </button>
          </form>
        )}
        {!registered || !isRegister ? (
          <p className="auth-switch">
            {isRegister ? 'Already have an account?' : 'New to TicketFlow?'}{' '}
            <Link to={isRegister ? '/login' : '/register'}>{isRegister ? 'Sign in' : 'Create an account'}</Link>
          </p>
        ) : null}
        <p className="auth-security">Your password is sent only to TicketFlow’s authentication endpoint.</p>
      </section>
      <aside className="auth-side">
        <span className="auth-side-kicker">MAKE TIME FOR WHAT MOVES YOU</span>
        <div className="auth-side-shape"><span /><i /><b /></div>
        <p>Some nights become stories you tell for years.</p>
      </aside>
    </div>
  )
}
