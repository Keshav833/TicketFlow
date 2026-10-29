import { ArrowRight, CalendarCheck2, Search, ShieldCheck, Sparkles } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { EventCard } from '../components/EventCard'
import { EmptyState, ErrorState, SkeletonCards } from '../components/Feedback'
import type { EventRecord } from '../types'
import { getApiErrorMessage } from '../api/client'

export function HomePage() {
  const [events, setEvents] = useState<EventRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  const loadEvents = () => {
    setLoading(true)
    setError('')
    api.listEvents({ starts_after: new Date().toISOString(), ordering: 'starts_at' })
      .then(({ data }) => setEvents(data.results))
      .catch((cause: unknown) => setError(getApiErrorMessage(cause)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadEvents()
  }, [])

  const search = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const value = query.trim()
    navigate(value ? `/events?search=${encodeURIComponent(value)}` : '/events')
  }

  const featured = events.slice(0, 3)
  const upcoming = events.slice(3, 9)

  return (
    <>
      <section className="home-hero">
        <div className="hero-orbit hero-orbit-one" />
        <div className="hero-orbit hero-orbit-two" />
        <div className="content-wrap hero-content">
          <div className="hero-copy">
            <span className="hero-label"><Sparkles size={15} /> YOUR NEXT GREAT NIGHT STARTS HERE</span>
            <h1>Find your people.<br /><span>Feel the moment.</span></h1>
            <p>From front-row sounds to big ideas, discover the moments worth showing up for.</p>
            <form className="hero-search" onSubmit={search} role="search">
              <Search size={20} aria-hidden="true" />
              <label className="sr-only" htmlFor="home-search">Search events</label>
              <input
                id="home-search"
                placeholder="What are you in the mood for?"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <button className="button button-primary" type="submit">Find events</button>
            </form>
            <div className="hero-proof">
              <span><ShieldCheck size={16} /> Secure checkout</span>
              <span><CalendarCheck2 size={16} /> Easy booking</span>
            </div>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="hero-art-card hero-art-card-back">
              <span className="art-sun" />
              <span className="art-lines" />
            </div>
            <div className="hero-art-card hero-art-card-front">
              <span className="art-caption">LIVE / TOGETHER</span>
              <span className="art-spotlight" />
              <span className="art-wave art-wave-one" />
              <span className="art-wave art-wave-two" />
              <span className="art-wave art-wave-three" />
              <span className="art-card-footer">MAKE IT A NIGHT.</span>
            </div>
            <span className="hero-art-chip">Good things happen live <Sparkles size={14} /></span>
          </div>
        </div>
        <div className="hero-bottom content-wrap">
          <span>CURATED FOR YOUR CALENDAR</span>
          <span className="hero-bottom-line" />
          <span>THE BEST PLANS ARE THE ONES YOU MAKE</span>
        </div>
      </section>

      <section className="section-block content-wrap">
        <div className="section-heading">
          <div>
            <p className="eyebrow">DON’T MISS OUT</p>
            <h2>Events worth going out for</h2>
            <p className="section-description">A first look at what’s coming up. Your next story might be right here.</p>
          </div>
          <Link className="text-link section-link" to="/events">Explore all events <ArrowRight size={16} /></Link>
        </div>
        {loading ? <SkeletonCards /> : error ? <ErrorState message={error} onRetry={loadEvents} /> : events.length === 0 ? (
          <EmptyState
            title="The calendar is taking a breather"
            description="There aren’t any events to show right now. Check back soon for something special."
          />
        ) : (
          <>
            <div className="event-grid">
              {featured.map((event) => <EventCard key={event.id} event={event} />)}
            </div>
            {upcoming.length > 0 && (
              <div className="upcoming-strip">
                <div className="upcoming-intro">
                  <p className="eyebrow">COMING UP NEXT</p>
                  <h3>More on the calendar</h3>
                </div>
                <div className="upcoming-list">
                  {upcoming.slice(0, 3).map((event) => (
                    <Link to={`/events/${event.id}`} className="upcoming-row" key={event.id}>
                      <span className="upcoming-date">
                        <strong>{new Intl.DateTimeFormat('en-IN', { day: '2-digit' }).format(new Date(event.starts_at))}</strong>
                        <small>{new Intl.DateTimeFormat('en-IN', { month: 'short' }).format(new Date(event.starts_at))}</small>
                      </span>
                      <span className="upcoming-title">
                        <strong>{event.name}</strong><small>{event.venue_name}</small>
                      </span>
                      <ArrowRight size={17} aria-hidden="true" />
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </section>

      <section className="why-section">
        <div className="content-wrap why-inner">
          <div>
            <p className="eyebrow">A BETTER WAY TO GO</p>
            <h2>All the good stuff.<br />None of the guesswork.</h2>
          </div>
          <div className="benefit-grid">
            <article><span className="benefit-number">01</span><h3>Find your thing</h3><p>Browse real events and the details that help you choose well.</p></article>
            <article><span className="benefit-number">02</span><h3>Book with confidence</h3><p>Your seats are held while you complete a secure checkout.</p></article>
            <article><span className="benefit-number">03</span><h3>Keep plans together</h3><p>See your booking status and event details in one place.</p></article>
          </div>
        </div>
      </section>
    </>
  )
}
