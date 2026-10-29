import { ArrowLeft, ArrowRight, Armchair, ShieldCheck } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { getApiErrorMessage } from '../api/client'
import { ErrorState, LoadingState } from '../components/Feedback'
import type { EventRecord, EventSeat } from '../types'
import { formatINR } from '../utils/format'

const backendPageSize = 10
const selectionLimit = 10

export function SeatSelectionPage() {
  const { eventId = '' } = useParams()
  const id = Number(eventId)
  const navigate = useNavigate()
  const [event, setEvent] = useState<EventRecord | null>(null)
  const [seats, setSeats] = useState<EventSeat[]>([])
  const [selected, setSelected] = useState<Record<number, EventSeat>>({})
  const [page, setPage] = useState(1)
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [holdError, setHoldError] = useState('')

  const load = () => {
    if (!Number.isInteger(id) || id < 1) {
      setError('This event could not be found.')
      setLoading(false)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError('')
    Promise.all([
      api.event(id, { signal: controller.signal }),
      api.eventSeats(id, page, { signal: controller.signal }),
    ])
      .then(([eventResponse, seatResponse]) => {
        setEvent(eventResponse.data)
        setSeats(seatResponse.data.results)
        setCount(seatResponse.data.count)
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(getApiErrorMessage(cause))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }

  useEffect(() => load(), [id, page])

  const selectedSeats = Object.values(selected)
  const total = selectedSeats.reduce((sum, seat) => sum + Number(seat.price), 0)
  const rows = useMemo(() => seats.reduce<Record<string, EventSeat[]>>((grouped, seat) => {
    ;(grouped[seat.seat_row] ??= []).push(seat)
    return grouped
  }, {}), [seats])
  const pageCount = Math.ceil(count / backendPageSize)

  const toggleSeat = (seat: EventSeat) => {
    setHoldError('')
    if (!selected[seat.id] && selectedSeats.length >= selectionLimit) {
      setHoldError(`You can select up to ${selectionLimit} seats at a time.`)
      return
    }
    setSelected((current) => {
      if (current[seat.id]) {
        const next = { ...current }
        delete next[seat.id]
        return next
      }
      return { ...current, [seat.id]: seat }
    })
  }

  const createHold = async () => {
    if (submitting || selectedSeats.length === 0) return
    setSubmitting(true)
    setHoldError('')
    try {
      const { data } = await api.createHold(id, selectedSeats.map((seat) => seat.id))
      navigate(`/checkout/${data.id}`)
    } catch (cause) {
      setHoldError(getApiErrorMessage(cause))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <div className="content-wrap page-section"><LoadingState label="Checking availability" /></div>
  if (error || !event) {
    return <div className="content-wrap page-section"><ErrorState message={error || 'This event could not be found.'} onRetry={load} /></div>
  }

  return (
    <div className="content-wrap page-section">
      <Link to={`/events/${event.id}`} className="back-link"><ArrowLeft size={16} /> Back to event</Link>
      <div className="page-heading compact-heading">
        <p className="eyebrow">STEP 1 OF 3 · SELECT YOUR SEATS</p>
        <h1>{event.name}</h1>
        <p>Choose up to {selectionLimit} seats. Availability is checked again when your hold is created.</p>
      </div>
      <div className="seat-layout">
        <section className="seat-map-panel">
          <div className="seat-legend" aria-label="Seat availability legend">
            <span><i className="legend-dot available-dot" /> Available</span>
            <span><i className="legend-dot selected-dot" /> Selected</span>
            <span><i className="legend-dot unavailable-dot" /> Held or sold</span>
          </div>
          <div className="stage">STAGE</div>
          <div className="seat-groups" aria-label="Seats on this page">
            {Object.entries(rows).map(([row, rowSeats]) => (
              <div className="seat-row" key={row}>
                <span className="row-label">ROW {row}</span>
                <div className="seat-row-items">
                  {rowSeats.map((seat) => {
                    const isSelected = Boolean(selected[seat.id])
                    const unavailable = seat.availability_status !== 'available'
                    return (
                      <button
                        key={seat.id}
                        type="button"
                        className={`seat-button ${isSelected ? 'seat-selected' : ''} ${unavailable ? 'seat-unavailable' : ''}`}
                        disabled={unavailable}
                        aria-pressed={isSelected}
                        aria-label={`Row ${seat.seat_row}, seat ${seat.seat_number}, ${seat.availability_status}, ${formatINR(seat.price)}`}
                        title={`${seat.ticket_tier_name} · ${formatINR(seat.price)}`}
                        onClick={() => toggleSeat(seat)}
                      >
                        {seat.seat_number}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
          {pageCount > 1 && (
            <div className="seat-pagination">
              <button className="button button-secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>
                <ArrowLeft size={15} /> Previous seats
              </button>
              <span>Page {page} of {pageCount}</span>
              <button className="button button-secondary" disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)}>
                More seats <ArrowRight size={15} />
              </button>
            </div>
          )}
          <details className="accessible-seat-list">
            <summary><Armchair size={16} /> Open accessible seat list</summary>
            <ul>
              {seats.map((seat) => (
                <li key={seat.id}>
                  Row {seat.seat_row}, seat {seat.seat_number} — {seat.ticket_tier_name}, {formatINR(seat.price)}, {seat.availability_status}
                </li>
              ))}
            </ul>
          </details>
        </section>
        <aside className="selection-summary">
          <p className="eyebrow">YOUR SELECTION</p>
          <h2>{selectedSeats.length} {selectedSeats.length === 1 ? 'seat' : 'seats'}</h2>
          {selectedSeats.length ? (
            <>
              <div className="selected-seat-list">
                {selectedSeats.map((seat) => (
                  <div key={seat.id}><span>Row {seat.seat_row} · Seat {seat.seat_number}</span><strong>{formatINR(seat.price)}</strong></div>
                ))}
              </div>
              <div className="total-line"><span>Estimated total</span><strong>{formatINR(total)}</strong></div>
            </>
          ) : (
            <p className="selection-empty">Tap any available seat to add it to your booking.</p>
          )}
          {holdError && <p className="form-error" role="alert">{holdError}</p>}
          <button className="button button-primary button-full" disabled={!selectedSeats.length || submitting} onClick={createHold}>
            {submitting ? 'Checking seats…' : 'Hold & continue'} <ArrowRight size={17} />
          </button>
          <p className="secure-note"><ShieldCheck size={14} /> Your booking price is confirmed by the server.</p>
        </aside>
      </div>
    </div>
  )
}
