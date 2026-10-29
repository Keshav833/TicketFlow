import { ArrowUpRight, CalendarDays, MapPin } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { EventRecord } from '../types'
import { formatDate, formatINR, formatTime } from '../utils/format'

export function EventCard({
  event,
  price,
}: {
  event: EventRecord
  price?: string | null
}) {
  return (
    <article className="event-card">
      <Link
        className={`event-poster poster-tone-${event.id % 5}`}
        to={`/events/${event.id}`}
        aria-label={`View ${event.name}`}
      >
        <span className="poster-kicker">TICKETFLOW / LIVE</span>
        <span className="poster-mark" aria-hidden="true">{event.name.slice(0, 1)}</span>
        <span className="poster-date">{formatDate(event.starts_at)}</span>
      </Link>
      <div className="event-card-body">
        <div className="event-card-heading">
          <h3><Link to={`/events/${event.id}`}>{event.name}</Link></h3>
          <Link className="icon-link" to={`/events/${event.id}`} aria-label={`Details for ${event.name}`}>
            <ArrowUpRight size={17} />
          </Link>
        </div>
        <div className="event-meta">
          <CalendarDays size={15} aria-hidden="true" />
          <span>{formatDate(event.starts_at)} · {formatTime(event.starts_at)}</span>
        </div>
        <div className="event-meta">
          <MapPin size={15} aria-hidden="true" />
          <span>{event.venue_name}</span>
        </div>
        <div className="event-card-bottom">
          {price ? <span>From <strong>{formatINR(price)}</strong></span> : <span>Explore tickets</span>}
          <Link to={`/events/${event.id}`} className="text-link">View event</Link>
        </div>
      </div>
    </article>
  )
}
