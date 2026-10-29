import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, CheckCircle2, Clock3, RefreshCw, ShieldCheck, TicketCheck } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { getApiErrorMessage } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { EmptyState, ErrorState, LoadingState } from '../components/Feedback'
import type { Booking, EventRecord } from '../types'
import { formatCountdown, formatDate, formatINR, formatTime } from '../utils/format'

function BookingStatus({ status }: { status: Booking['status'] }) {
  const labels: Record<Booking['status'], string> = {
    held: 'Seat held',
    payment_pending: 'Payment pending',
    confirmed: 'Confirmed',
    expired: 'Expired',
    cancelled: 'Cancelled',
    refunded: 'Refunded',
  }
  return <span className={`status-pill status-${status}`}>{labels[status]}</span>
}

function BookingItems({ booking }: { booking: Booking }) {
  return (
    <div className="booking-items">
      {booking.items.map((item) => (
        <div className="booking-item" key={item.id}>
          <span><strong>Row {item.seat_row} · Seat {item.seat_number}</strong><small>{item.event_name}</small></span>
          <strong>{formatINR(item.price)}</strong>
        </div>
      ))}
      <div className="total-line"><span>Total</span><strong>{formatINR(booking.total_amount)}</strong></div>
    </div>
  )
}

export function CheckoutPage() {
  const { bookingId = '' } = useParams()
  const id = Number(bookingId)
  const { user } = useAuth()
  const navigate = useNavigate()
  const [booking, setBooking] = useState<Booking | null>(null)
  const [event, setEvent] = useState<EventRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [reload, setReload] = useState(0)

  const load = useCallback(async () => {
    if (!Number.isInteger(id) || id < 1) {
      setError('This booking could not be found.')
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const { data } = await api.booking(id)
      setBooking(data)
      if (data.items[0]?.event_id) {
        const eventResponse = await api.event(data.items[0].event_id)
        setEvent(eventResponse.data)
      }
    } catch (cause) {
      setError(getApiErrorMessage(cause))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { void load() }, [load, reload])
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const remaining = booking?.hold_expires_at
    ? new Date(booking.hold_expires_at).getTime() - now
    : null
  const holdExpired = booking?.status === 'held' && remaining !== null && remaining <= 0

  const refreshStatus = async () => {
    setNotice('')
    try {
      const { data } = await api.booking(id)
      setBooking(data)
      if (data.status === 'confirmed') navigate(`/booking-confirmation/${id}`, { replace: true })
      else setNotice(`Current booking status: ${data.status.replace('_', ' ')}. Payment may still be processing.`)
    } catch (cause) {
      setError(getApiErrorMessage(cause))
    }
  }

  const openCheckout = async () => {
    if (busy || !booking || (booking.status !== 'held' && booking.status !== 'payment_pending')) return
    if (holdExpired) {
      setError('This seat hold has expired. Return to the event to check availability and book again.')
      return
    }
    setError('')
    setNotice('')
    setBusy(true)
    try {
      const { data: order } = await api.createPaymentOrder(id)
      await loadRazorpay()
      if (!window.Razorpay) throw new Error('Razorpay Checkout did not initialize.')
      const checkout = new window.Razorpay({
        key: order.razorpay_key_id,
        amount: order.amount,
        currency: order.currency,
        name: 'TicketFlow',
        description: event?.name || 'Event booking',
        order_id: order.razorpay_order_id,
        prefill: { name: user?.username, email: user?.email },
        theme: { color: '#4f46e5' },
        handler: async (result) => {
          try {
            const { data: verification } = await api.verifyPayment({
              booking_id: id,
              razorpay_order_id: result.razorpay_order_id,
              razorpay_payment_id: result.razorpay_payment_id,
              razorpay_signature: result.razorpay_signature,
            })
            if (verification.booking_status === 'confirmed') {
              navigate(`/booking-confirmation/${id}`, { replace: true })
              return
            }
            setNotice('Payment was submitted, but the booking is not confirmed yet. Refresh the booking status before trying again.')
            setBusy(false)
          } catch (cause) {
            setError(getApiErrorMessage(cause))
            setNotice('Checkout returned a payment result, but verification could not be confirmed. Refresh the booking status before retrying.')
            setBusy(false)
          }
        },
        modal: {
          ondismiss: () => {
            setBusy(false)
            setNotice('Checkout was closed. If you completed payment, refresh the booking status before starting another attempt.')
            void refreshStatus()
          },
        },
      })
      checkout.on('payment.failed', (response) => {
        setBusy(false)
        setError(response.error?.description || 'Payment was not completed.')
        void refreshStatus()
      })
      checkout.open()
    } catch (cause) {
      setBusy(false)
      setError(getApiErrorMessage(cause))
    }
  }

  if (loading) return <div className="content-wrap page-section"><LoadingState label="Loading your booking" /></div>
  if (error && !booking) return <div className="content-wrap page-section"><ErrorState message={error} onRetry={() => setReload((value) => value + 1)} /></div>
  if (!booking) return <div className="content-wrap page-section"><EmptyState title="Booking unavailable" description="This booking could not be loaded." /></div>

  return (
    <div className="content-wrap page-section narrow-page">
      <Link to={event ? `/events/${event.id}` : '/my-bookings'} className="back-link"><ArrowLeft size={16} /> Back</Link>
      <div className="page-heading compact-heading">
        <p className="eyebrow">STEP 2 OF 3 · REVIEW & PAY</p>
        <h1>Review your booking</h1>
        <p>Booking #{booking.id} · {event?.name || booking.items[0]?.event_name}</p>
      </div>
      <section className="checkout-card">
        <div className="checkout-status">
          <span className="status-icon"><TicketCheck size={20} /></span>
          <span><strong>Your seats are together</strong><small>Final price and availability are managed by TicketFlow.</small></span>
          <BookingStatus status={booking.status} />
        </div>
        {event && (
          <div className="checkout-event">
            <strong>{event.name}</strong>
            <span>{formatDate(event.starts_at)} · {formatTime(event.starts_at)}</span>
          </div>
        )}
        <BookingItems booking={booking} />
        {booking.status === 'held' && remaining !== null && (
          <div className={`hold-countdown ${holdExpired ? 'countdown-expired' : ''}`} role="status">
            <Clock3 size={18} />
            <span>{holdExpired ? 'Your seat hold has expired' : 'Complete payment before your seat hold expires'}</span>
            <strong>{holdExpired ? '00:00' : formatCountdown(remaining)}</strong>
          </div>
        )}
        {error && <p className="form-error" role="alert">{error}</p>}
        {notice && <p className="notice-message" role="status">{notice}</p>}
        {(booking.status === 'held' || booking.status === 'payment_pending') && (
          <button className="button button-primary button-full checkout-button" disabled={busy || holdExpired} onClick={openCheckout}>
            {busy ? 'Waiting for payment…' : booking.status === 'payment_pending' ? 'Continue secure payment' : 'Continue to secure payment'}
            <ArrowRight size={17} />
          </button>
        )}
        {booking.status !== 'held' && booking.status !== 'payment_pending' && (
          <Link className="button button-secondary button-full" to={`/booking-confirmation/${id}`}>View booking status</Link>
        )}
        <button className="button button-quiet button-full" onClick={refreshStatus}>
          <RefreshCw size={15} /> Refresh booking status
        </button>
        <p className="secure-note"><ShieldCheck size={14} /> Payment is confirmed only after TicketFlow verifies it with Razorpay.</p>
      </section>
    </div>
  )
}

function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve()
  return new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.async = true
    script.onload = () => window.Razorpay ? resolve() : reject(new Error('Razorpay Checkout did not initialize.'))
    script.onerror = () => reject(new Error('Unable to load Razorpay Checkout. Check your connection and try again.'))
    document.body.appendChild(script)
  })
}

export function ConfirmationPage() {
  const { bookingId = '' } = useParams()
  const id = Number(bookingId)
  const [booking, setBooking] = useState<Booking | null>(null)
  const [event, setEvent] = useState<EventRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    api.booking(id)
      .then(async ({ data }) => {
        setBooking(data)
        if (data.items[0]?.event_id) {
          const eventResponse = await api.event(data.items[0].event_id)
          setEvent(eventResponse.data)
        }
      })
      .catch((cause: unknown) => setError(getApiErrorMessage(cause)))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="content-wrap page-section"><LoadingState label="Checking booking status" /></div>
  if (error || !booking) return <div className="content-wrap page-section"><ErrorState message={error || 'Booking unavailable.'} onRetry={load} /></div>

  const confirmed = booking.status === 'confirmed'

  return (
    <div className="content-wrap page-section narrow-page">
      <section className={`confirmation-card ${confirmed ? 'confirmed-card' : ''}`}>
        <span className="confirmation-mark">{confirmed ? <CheckCircle2 size={30} /> : <Clock3 size={28} />}</span>
        <p className="eyebrow">{confirmed ? 'YOU’RE ALL SET' : 'BOOKING STATUS'}</p>
        <h1>{confirmed ? 'It’s happening.' : booking.status === 'payment_pending' ? 'Payment is processing' : 'Booking not confirmed'}</h1>
        <p className="confirmation-copy">
          {confirmed
            ? 'Your payment has been verified and your booking is confirmed.'
            : booking.status === 'payment_pending'
              ? 'We have not received final confirmation yet. Refresh this page to check for an update.'
              : `TicketFlow reports this booking as ${booking.status.replace('_', ' ')}. No confirmation is implied.`}
        </p>
        <div className="confirmation-reference"><span>Booking reference</span><strong>TF-{booking.id}</strong></div>
        {event && (
          <div className="confirmed-event">
            <span className="confirmed-event-icon"><TicketCheck size={18} /></span>
            <span><strong>{event.name}</strong><small>{formatDate(event.starts_at)} · {formatTime(event.starts_at)}</small></span>
          </div>
        )}
        <BookingItems booking={booking} />
        {!confirmed && (
          <button className="button button-secondary button-full" onClick={load}><RefreshCw size={16} /> Refresh status</button>
        )}
        <div className="confirmation-actions">
          <Link className="button button-primary" to="/my-bookings">My bookings</Link>
          <Link className="button button-secondary" to="/events">Discover more events</Link>
        </div>
        <p className="ticket-note">Tickets and QR codes are not provided by the current API.</p>
      </section>
    </div>
  )
}

export function BookingHistoryPage() {
  const [bookings, setBookings] = useState<Booking[]>([])
  const [page, setPage] = useState(1)
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const pageSize = 10

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    api.bookings({ params: { page } })
      .then(({ data }) => {
        setBookings(data.results)
        setCount(data.count)
      })
      .catch((cause: unknown) => setError(getApiErrorMessage(cause)))
      .finally(() => setLoading(false))
  }, [page])

  useEffect(() => { load() }, [load])

  const pageCount = Math.ceil(count / pageSize)

  return (
    <div className="content-wrap page-section">
      <div className="page-heading">
        <p className="eyebrow">YOUR PLANS, ALL TOGETHER</p>
        <h1>My bookings</h1>
        <p>Keep track of your seats and the moments you’re looking forward to.</p>
      </div>
      {loading ? <LoadingState label="Loading bookings" /> : error ? <ErrorState message={error} onRetry={load} /> : bookings.length === 0 ? (
        <EmptyState title="Nothing booked yet" description="When you find an event you love, your bookings will show up here." action={<Link className="button button-primary" to="/events">Explore events</Link>} />
      ) : (
        <>
          <div className="booking-list">
            {bookings.map((booking) => {
              const firstItem = booking.items[0]
              return (
                <article className="booking-history-card" key={booking.id}>
                  <div className="booking-history-main">
                    <span className="booking-ticket-icon"><TicketCheck size={20} /></span>
                    <div>
                      <p className="eyebrow">BOOKING TF-{booking.id}</p>
                      <h2>{firstItem?.event_name || 'Event booking'}</h2>
                      <p>{booking.items.length} {booking.items.length === 1 ? 'seat' : 'seats'} · {booking.items.map((item) => `${item.seat_row}${item.seat_number}`).join(', ')}</p>
                    </div>
                  </div>
                  <div className="booking-history-meta">
                    <BookingStatus status={booking.status} />
                    <strong>{formatINR(booking.total_amount)}</strong>
                    <Link className="text-link" to={`/my-bookings/${booking.id}`}>View details <ArrowRight size={15} /></Link>
                  </div>
                </article>
              )
            })}
          </div>
          {pageCount > 1 && (
            <div className="pagination">
              <button className="button button-secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ArrowLeft size={16} /> Previous</button>
              <span>Page {page} of {pageCount}</span>
              <button className="button button-secondary" disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)}>Next <ArrowRight size={16} /></button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export function BookingDetailsPage() {
  const { bookingId = '' } = useParams()
  const id = Number(bookingId)
  const [booking, setBooking] = useState<Booking | null>(null)
  const [event, setEvent] = useState<EventRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    setLoading(true)
    setError('')
    api.booking(id)
      .then(async ({ data }) => {
        setBooking(data)
        if (data.items[0]?.event_id) {
          const eventResponse = await api.event(data.items[0].event_id)
          setEvent(eventResponse.data)
        }
      })
      .catch((cause: unknown) => setError(getApiErrorMessage(cause)))
      .finally(() => setLoading(false))
  }, [id, reload])

  if (loading) return <div className="content-wrap page-section"><LoadingState label="Loading booking details" /></div>
  if (error || !booking) return <div className="content-wrap page-section"><ErrorState message={error || 'Booking unavailable.'} onRetry={() => setReload((value) => value + 1)} /></div>

  return (
    <div className="content-wrap page-section narrow-page">
      <Link to="/my-bookings" className="back-link"><ArrowLeft size={16} /> My bookings</Link>
      <div className="page-heading compact-heading">
        <p className="eyebrow">BOOKING TF-{booking.id}</p>
        <h1>{event?.name || booking.items[0]?.event_name || 'Booking details'}</h1>
      </div>
      <section className="checkout-card">
        <div className="checkout-status">
          <span><strong>Booking status</strong><small>Updated {formatDate(booking.updated_at)}</small></span>
          <BookingStatus status={booking.status} />
        </div>
        {event && <div className="checkout-event"><strong>{event.name}</strong><span>{formatDate(event.starts_at)} · {formatTime(event.starts_at)}</span></div>}
        <BookingItems booking={booking} />
        <div className="booking-detail-actions">
          {booking.status === 'held' && <Link className="button button-primary button-full" to={`/checkout/${booking.id}`}>Continue to payment <ArrowRight size={17} /></Link>}
          {booking.status === 'payment_pending' && (
            <Link className="button button-primary button-full" to={`/checkout/${booking.id}`}>Continue payment <ArrowRight size={17} /></Link>
          )}
          {booking.status === 'confirmed' && <Link className="button button-primary button-full" to={`/booking-confirmation/${booking.id}`}>View confirmation <ArrowRight size={17} /></Link>}
          <Link to="/events" className="button button-secondary button-full">Browse events</Link>
        </div>
        <p className="ticket-note">Only booking actions supported by the current API are shown. Ticket downloads and refunds are not exposed.</p>
      </section>
    </div>
  )
}
