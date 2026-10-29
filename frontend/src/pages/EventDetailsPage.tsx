import { ArrowRight, CalendarDays, Clock3, MapPin, TicketCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { getApiErrorMessage } from '../api/client'
import { ErrorState, LoadingState } from '../components/Feedback'
import type { EventRecord, Venue } from '../types'
import { formatDate, formatTime } from '../utils/format'

export function EventDetailsPage() {
  const { eventId = '' } = useParams()
  const id = Number(eventId)
  const [event, setEvent] = useState<EventRecord | null>(null)
  const [venue, setVenue] = useState<Venue | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    if (!Number.isInteger(id) || id < 1) {
      setLoading(false)
      setError('This event could not be found.')
      return
    }
    setLoading(true)
    setError('')
    api.event(id)
      .then(async (eventResponse) => {
        setEvent(eventResponse.data)
        const venueResponse = await api.venue(eventResponse.data.venue)
        setVenue(venueResponse.data)
      })
      .catch((cause: unknown) => setError(getApiErrorMessage(cause)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [id])

  if (loading) return <div className="content-wrap page-section"><LoadingState label="Loading event" /></div>
  if (error || !event) {
    return <div className="content-wrap page-section"><ErrorState message={error || 'This event could not be found.'} onRetry={load} /></div>
  }

  return (
    <div className="content-wrap page-section">
      <div className={`event-detail-banner poster-tone-${event.id % 5}`}>
        <span className="banner-kicker">TICKETFLOW PRESENTS</span>
        <span className="banner-glyph" aria-hidden="true">{event.name.slice(0, 1)}</span>
        <span className="banner-bottom">MAKE THE MOMENT YOURS</span>
      </div>
      <div className="event-detail-grid">
        <article className="event-detail-main">
          <p className="eyebrow">THE EXPERIENCE</p>
          <h1>{event.name}</h1>
          <div className="detail-meta-list">
            <div><CalendarDays size={18} /><span><strong>{formatDate(event.starts_at)}</strong><small>Event date</small></span></div>
            <div><Clock3 size={18} /><span><strong>{formatTime(event.starts_at)} – {formatTime(event.ends_at)}</strong><small>Local event time</small></span></div>
            <div><MapPin size={18} /><span><strong>{venue?.name || event.venue_name}</strong><small>{venue ? `${venue.city} · ${venue.address}` : 'Venue details'}</small></span></div>
          </div>
          <section className="description-section">
            <h2>About this event</h2>
            <p>{event.description || 'More details about this event will be shared soon. Save your seat and get ready for a memorable experience.'}</p>
          </section>
          <div className="booking-guidance">
            <TicketCheck size={19} />
            <p>Select your available seats in the next step. A seat hold is created only when you confirm your selection.</p>
          </div>
        </article>
        <aside className="booking-summary-card">
          <p className="eyebrow">YOUR NIGHT OUT</p>
          <h2>Be there for it.</h2>
          <p className="starting-price">See live seat availability and ticket prices before you book.</p>
          <div className="summary-rule" />
          <p className="summary-note">Available seats and current pricing are confirmed by TicketFlow before booking.</p>
          <Link className="button button-primary button-full" to={`/events/${event.id}/seats`}>
            Choose seats <ArrowRight size={17} />
          </Link>
          <p className="secure-note">Secure payment handled by Razorpay</p>
        </aside>
      </div>
    </div>
  )
}
