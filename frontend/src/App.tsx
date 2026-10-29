import { Component, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth/AuthProvider'
import { Layout } from './components/Layout'
import { LoadingState } from './components/Feedback'
import { AuthPage } from './pages/AuthPage'
import { BookingDetailsPage, BookingHistoryPage, CheckoutPage, ConfirmationPage } from './pages/BookingPages'
import { EventDetailsPage } from './pages/EventDetailsPage'
import { EventsPage } from './pages/EventsPage'
import { HomePage } from './pages/HomePage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ProfilePage } from './pages/ProfilePage'
import { SeatSelectionPage } from './pages/SeatSelectionPage'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <LoadingState label="Restoring your session" />
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  return children
}

class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="fatal-error">
          <div className="content-wrap">
            <p className="eyebrow">Something went wrong</p>
            <h1>Let’s get you back on track.</h1>
            <p>This page ran into an unexpected error. Reload it or head back to discover events.</p>
            <button className="button button-primary" onClick={() => window.location.assign('/')}>
              Back to TicketFlow
            </button>
          </div>
        </main>
      )
    }
    return this.props.children
  }
}

export function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="events" element={<EventsPage />} />
          <Route path="events/:eventId" element={<EventDetailsPage />} />
          <Route path="events/:eventId/seats" element={
            <ProtectedRoute><SeatSelectionPage /></ProtectedRoute>
          } />
          <Route path="login" element={<AuthPage mode="login" />} />
          <Route path="register" element={<AuthPage mode="register" />} />
          <Route path="checkout/:bookingId" element={
            <ProtectedRoute><CheckoutPage /></ProtectedRoute>
          } />
          <Route path="booking-confirmation/:bookingId" element={
            <ProtectedRoute><ConfirmationPage /></ProtectedRoute>
          } />
          <Route path="my-bookings" element={
            <ProtectedRoute><BookingHistoryPage /></ProtectedRoute>
          } />
          <Route path="my-bookings/:bookingId" element={
            <ProtectedRoute><BookingDetailsPage /></ProtectedRoute>
          } />
          <Route path="profile" element={
            <ProtectedRoute><ProfilePage /></ProtectedRoute>
          } />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  )
}
