import { ArrowLeft, ArrowRight, Search, SlidersHorizontal } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { getApiErrorMessage } from '../api/client'
import { EventCard } from '../components/EventCard'
import { EmptyState, ErrorState, SkeletonCards } from '../components/Feedback'
import type { EventRecord, Venue } from '../types'

const pageSize = 10

function toDateTime(value: string, lastMoment = false) {
  if (!value) return undefined
  const date = new Date(`${value}T${lastMoment ? '23:59:59' : '00:00:00'}`)
  return date.toISOString()
}

export function EventsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const page = Math.max(1, Number(searchParams.get('page')) || 1)
  const search = searchParams.get('search') || ''
  const venueFilter = searchParams.get('venue') || ''
  const ordering = (searchParams.get('ordering') || 'starts_at') as 'starts_at' | '-starts_at' | 'name'
  const fromDate = searchParams.get('from') || ''
  const untilDate = searchParams.get('until') || ''
  const [searchInput, setSearchInput] = useState(search)
  const [events, setEvents] = useState<EventRecord[]>([])
  const [venues, setVenues] = useState<Venue[]>([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [venueError, setVenueError] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => setSearchInput(search), [search])

  useEffect(() => {
    const controller = new AbortController()
    api.listVenues({ signal: controller.signal })
      .then(({ data }) => setVenues(data.results))
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setVenueError(getApiErrorMessage(cause))
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    api.listEvents({
      page,
      search: search || undefined,
      venue: venueFilter ? Number(venueFilter) : undefined,
      starts_after: toDateTime(fromDate),
      starts_before: toDateTime(untilDate, true),
      ordering,
    }, { signal: controller.signal })
      .then(({ data }) => {
        setEvents(data.results)
        setCount(data.count)
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(getApiErrorMessage(cause))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [page, search, venueFilter, fromDate, untilDate, ordering, reload])

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    setSearchParams(next)
  }

  const onSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    update('search', searchInput.trim())
  }

  const pageCount = Math.ceil(count / pageSize)

  return (
    <div className="content-wrap page-section">
      <div className="page-heading">
        <p className="eyebrow">FIND YOUR NEXT EXPERIENCE</p>
        <h1>Discover events</h1>
        <p>Explore what’s happening and save a seat for something memorable.</p>
      </div>
      <div className="discovery-layout">
        <aside className="filter-panel">
          <div className="filter-title"><SlidersHorizontal size={17} /><strong>Refine your search</strong></div>
          <form onSubmit={onSearch} className="filter-form">
            <label htmlFor="event-search">Search</label>
            <div className="filter-search">
              <Search size={17} />
              <input id="event-search" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Event or venue" />
            </div>
            <button type="submit" className="button button-primary filter-submit">Search events</button>
            <label htmlFor="venue-filter">Venue</label>
            <select id="venue-filter" value={venueFilter} onChange={(event) => update('venue', event.target.value)}>
              <option value="">All venues</option>
              {venues.map((venue) => <option value={venue.id} key={venue.id}>{venue.name} · {venue.city}</option>)}
            </select>
            <label htmlFor="from-filter">Starting after</label>
            <input id="from-filter" type="date" value={fromDate} onChange={(event) => update('from', event.target.value)} />
            <label htmlFor="until-filter">Starting before</label>
            <input id="until-filter" type="date" value={untilDate} onChange={(event) => update('until', event.target.value)} />
            <label htmlFor="sort-filter">Sort by</label>
            <select id="sort-filter" value={ordering} onChange={(event) => update('ordering', event.target.value)}>
              <option value="starts_at">Soonest first</option>
              <option value="-starts_at">Latest first</option>
              <option value="name">Name A–Z</option>
            </select>
          </form>
        </aside>
        <section className="results-panel" aria-live="polite">
          <div className="results-heading">
            <span>{count} {count === 1 ? 'event' : 'events'} found</span>
            {search && <span className="search-chip">“{search}” <button onClick={() => update('search', '')} aria-label="Clear search">×</button></span>}
          </div>
          {venueError && <p className="filter-warning" role="status">Venue filters could not be loaded: {venueError}</p>}
          {loading ? <SkeletonCards count={6} /> : error ? <ErrorState message={error} onRetry={() => setReload((value) => value + 1)} /> : events.length === 0 ? (
            <EmptyState title="No events match just yet" description="Try another search or loosen your filters." />
          ) : (
            <>
              <div className="event-grid">
                {events.map((event) => <EventCard key={event.id} event={event} />)}
              </div>
              {pageCount > 1 && (
                <div className="pagination">
                  <button className="button button-secondary" disabled={page <= 1} onClick={() => update('page', String(page - 1))}>
                    <ArrowLeft size={16} /> Previous
                  </button>
                  <span>Page {page} of {pageCount}</span>
                  <button className="button button-secondary" disabled={page >= pageCount} onClick={() => update('page', String(page + 1))}>
                    Next <ArrowRight size={16} />
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
