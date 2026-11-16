import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  Calendar,
  CheckCircle2,
  Clock,
  Download,
  ExternalLink,
  MapPin,
  Maximize2,
  Printer,
  QrCode,
  Ticket as TicketIcon,
  X,
  XCircle,
} from 'lucide-react'
import { api } from '../api'
import { getApiErrorMessage } from '../api/client'
import { EmptyState, ErrorState, LoadingState } from '../components/Feedback'
import type { CustomerTicket } from '../types'
import { formatDate, formatINR, formatTime } from '../utils/format'

export function TicketStatusBadge({ ticket }: { ticket: CustomerTicket }) {
  if (ticket.booking_status === 'refund_pending') {
    return <span className="status-pill status-held">Refund pending</span>
  }
  if (ticket.booking_status === 'refunded') {
    return <span className="status-pill status-cancelled">Refunded</span>
  }

  switch (ticket.status) {
    case 'issued':
      return <span className="status-pill status-confirmed">Confirmed</span>
    case 'used':
      return <span className="status-pill status-expired">Used</span>
    case 'cancelled':
      return <span className="status-pill status-cancelled">Cancelled</span>
    default:
      return <span className="status-pill status-expired">{ticket.status}</span>
  }
}

export function TicketWalletPage() {
  const [tickets, setTickets] = useState<CustomerTicket[]>([])
  const [count, setCount] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<'all' | 'issued' | 'used' | 'cancelled'>('all')
  const pageSize = 10

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    api
      .tickets({ params: { page } })
      .then(({ data }) => {
        setTickets(data.results)
        setCount(data.count)
      })
      .catch((cause: unknown) => setError(getApiErrorMessage(cause)))
      .finally(() => setLoading(false))
  }, [page])

  useEffect(() => {
    load()
  }, [load])

  const filteredTickets = tickets.filter((ticket) => {
    if (filter === 'all') return true
    return ticket.status === filter
  })

  const pageCount = Math.ceil(count / pageSize)

  return (
    <div className="content-wrap page-section">
      <div className="page-heading">
        <p className="eyebrow">DIGITAL TICKET WALLET</p>
        <h1>My tickets</h1>
        <p>Access your verified entry passes, view check-in QR codes, download PDFs, or print tickets.</p>
      </div>

      <div className="ticket-filter-bar no-print">
        <button
          type="button"
          className={`filter-chip ${filter === 'all' ? 'active' : ''}`}
          onClick={() => setFilter('all')}
        >
          All tickets ({tickets.length})
        </button>
        <button
          type="button"
          className={`filter-chip ${filter === 'issued' ? 'active' : ''}`}
          onClick={() => setFilter('issued')}
        >
          Active / Confirmed ({tickets.filter((t) => t.status === 'issued').length})
        </button>
        <button
          type="button"
          className={`filter-chip ${filter === 'used' ? 'active' : ''}`}
          onClick={() => setFilter('used')}
        >
          Used ({tickets.filter((t) => t.status === 'used').length})
        </button>
        <button
          type="button"
          className={`filter-chip ${filter === 'cancelled' ? 'active' : ''}`}
          onClick={() => setFilter('cancelled')}
        >
          Cancelled ({tickets.filter((t) => t.status === 'cancelled').length})
        </button>
      </div>

      {loading ? (
        <LoadingState label="Loading your tickets" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : tickets.length === 0 ? (
        <EmptyState
          title="Your ticket wallet is empty"
          description="Tickets for your confirmed event bookings will appear here automatically once payment is verified."
          action={
            <Link className="button button-primary" to="/events">
              Explore upcoming events
            </Link>
          }
        />
      ) : filteredTickets.length === 0 ? (
        <EmptyState
          title="No tickets match this filter"
          description="Try switching filters to view all your tickets."
          action={
            <button className="button button-secondary" onClick={() => setFilter('all')}>
              Show all tickets
            </button>
          }
        />
      ) : (
        <>
          <div className="ticket-wallet-grid">
            {filteredTickets.map((ticket) => (
              <article className="wallet-ticket-card" key={ticket.id}>
                <div className="wallet-ticket-header">
                  <div className="wallet-ticket-event">
                    <span className="wallet-ticket-icon">
                      <TicketIcon size={20} />
                    </span>
                    <div>
                      <p className="eyebrow">TICKET #{ticket.ticket_number}</p>
                      <h2>{ticket.event_name}</h2>
                    </div>
                  </div>
                  <TicketStatusBadge ticket={ticket} />
                </div>

                <div className="wallet-ticket-body">
                  <div className="wallet-ticket-detail-item">
                    <Calendar size={16} />
                    <span>{formatDate(ticket.event_starts_at)}</span>
                  </div>
                  <div className="wallet-ticket-detail-item">
                    <Clock size={16} />
                    <span>{formatTime(ticket.event_starts_at)}</span>
                  </div>
                  <div className="wallet-ticket-detail-item">
                    <MapPin size={16} />
                    <span>
                      {ticket.venue_name}, {ticket.venue_city}
                    </span>
                  </div>
                </div>

                <div className="wallet-ticket-seat-bar">
                  <div>
                    <small>Seat</small>
                    <strong>
                      Row {ticket.seat_row}, Seat {ticket.seat_number}
                    </strong>
                  </div>
                  <div>
                    <small>Tier</small>
                    <strong>{ticket.tier_name}</strong>
                  </div>
                  <div>
                    <small>Booking</small>
                    <strong>TF-{ticket.booking_id}</strong>
                  </div>
                  <div>
                    <small>Amount</small>
                    <strong>{formatINR(ticket.price)}</strong>
                  </div>
                </div>

                <div className="wallet-ticket-footer">
                  <Link className="button button-primary button-small" to={`/my-tickets/${ticket.id}`}>
                    <QrCode size={15} /> View ticket & QR
                  </Link>
                  <Link className="text-link" to={`/my-bookings/${ticket.booking_id}`}>
                    Booking details <ArrowRight size={14} />
                  </Link>
                </div>
              </article>
            ))}
          </div>

          {pageCount > 1 && (
            <div className="pagination no-print">
              <button
                className="button button-secondary"
                disabled={page <= 1}
                onClick={() => setPage((v) => v - 1)}
              >
                <ArrowLeft size={16} /> Previous
              </button>
              <span>
                Page {page} of {pageCount}
              </span>
              <button
                className="button button-secondary"
                disabled={page >= pageCount}
                onClick={() => setPage((v) => v + 1)}
              >
                Next <ArrowRight size={16} />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export function TicketDetailPage() {
  const { ticketId = '' } = useParams()
  const id = Number(ticketId)
  const [ticket, setTicket] = useState<CustomerTicket | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [qrUrl, setQrUrl] = useState<string | null>(null)
  const [qrLoading, setQrLoading] = useState(false)
  const [qrError, setQrError] = useState(false)
  const [enlargeQr, setEnlargeQr] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (!Number.isInteger(id) || id < 1) {
      setError('Invalid ticket reference.')
      setLoading(false)
      return
    }

    setLoading(true)
    setError('')
    api
      .ticket(id)
      .then(({ data }) => {
        setTicket(data)
        if (data.qr_available) {
          setQrLoading(true)
          setQrError(false)
          api
            .ticketQr(id)
            .then((res) => {
              const url = URL.createObjectURL(res.data)
              setQrUrl(url)
            })
            .catch(() => {
              setQrError(true)
            })
            .finally(() => setQrLoading(false))
        }
      })
      .catch((cause: unknown) => setError(getApiErrorMessage(cause)))
      .finally(() => setLoading(false))

    return () => {
      if (qrUrl) {
        URL.revokeObjectURL(qrUrl)
      }
    }
  }, [id, reload])

  const handleDownload = async () => {
    if (!ticket || downloading) return
    setDownloading(true)
    try {
      const res = await api.downloadTicket(ticket.id)
      const blob = new Blob([res.data], { type: 'application/pdf' })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `ticket-${ticket.ticket_number}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (cause) {
      alert(`Download failed: ${getApiErrorMessage(cause)}`)
    } finally {
      setDownloading(false)
    }
  }

  const handlePrint = () => {
    window.print()
  }

  if (loading) {
    return (
      <div className="content-wrap page-section">
        <LoadingState label="Loading ticket details" />
      </div>
    )
  }

  if (error || !ticket) {
    return (
      <div className="content-wrap page-section">
        <ErrorState
          message={error || 'Ticket not found.'}
          onRetry={() => setReload((v) => v + 1)}
        />
      </div>
    )
  }

  const isEligible = ticket.status === 'issued' && ticket.booking_status === 'confirmed'

  return (
    <div className="content-wrap page-section narrow-page">
      <Link to="/my-tickets" className="back-link no-print">
        <ArrowLeft size={16} /> My ticket wallet
      </Link>

      <div className="page-heading compact-heading no-print">
        <p className="eyebrow">BOARDING PASS & ENTRY TICKET</p>
        <h1>{ticket.event_name}</h1>
      </div>

      {/* Main Boarding Pass / Ticket Element */}
      <section className="boarding-pass" id="printable-ticket">
        <div className="boarding-pass-main">
          <div className="boarding-pass-top">
            <div className="pass-brand">
              <span className="brand-icon">
                <TicketIcon size={18} />
              </span>
              <span>ticketflow<span className="brand-period">.</span> entry pass</span>
            </div>
            <TicketStatusBadge ticket={ticket} />
          </div>

          <div className="pass-event-details">
            <h2 className="pass-title">{ticket.event_name}</h2>
            <div className="pass-meta-grid">
              <div className="pass-meta-item">
                <small>Date</small>
                <strong>{formatDate(ticket.event_starts_at)}</strong>
              </div>
              <div className="pass-meta-item">
                <small>Time</small>
                <strong>{formatTime(ticket.event_starts_at)}</strong>
              </div>
              <div className="pass-meta-item">
                <small>Venue</small>
                <strong>{ticket.venue_name}</strong>
                <span>{ticket.venue_city}</span>
              </div>
            </div>
          </div>

          <div className="pass-seat-strip">
            <div className="pass-seat-box">
              <small>ROW</small>
              <strong>{ticket.seat_row}</strong>
            </div>
            <div className="pass-seat-box">
              <small>SEAT</small>
              <strong>{ticket.seat_number}</strong>
            </div>
            <div className="pass-seat-box">
              <small>TIER</small>
              <strong>{ticket.tier_name}</strong>
            </div>
            <div className="pass-seat-box">
              <small>AMOUNT</small>
              <strong>{formatINR(ticket.price)}</strong>
            </div>
          </div>

          <div className="pass-footer-meta">
            <span>Ticket: <strong>{ticket.ticket_number}</strong></span>
            <span>Booking: <strong>TF-{ticket.booking_id}</strong></span>
            <span>Issued: {formatDate(ticket.issued_at)}</span>
          </div>
        </div>

        {/* Perforated Divider */}
        <div className="boarding-pass-divider" aria-hidden="true">
          <div className="notch notch-top" />
          <div className="perforation" />
          <div className="notch notch-bottom" />
        </div>

        {/* Boarding Pass Stub with QR */}
        <div className="boarding-pass-stub">
          <div className="pass-qr-wrapper">
            <p className="eyebrow pass-qr-heading">OFFICIAL QR PASS</p>
            {qrLoading ? (
              <div className="pass-qr-loading">
                <LoadingState label="Loading QR code" />
              </div>
            ) : qrUrl ? (
              <div className="pass-qr-box">
                <img
                  src={qrUrl}
                  alt={`QR code for ticket ${ticket.ticket_number}`}
                  className="pass-qr-image"
                />
                <button
                  type="button"
                  className="pass-qr-enlarge-btn no-print"
                  onClick={() => setEnlargeQr(true)}
                  title="Enlarge QR for scanning"
                >
                  <Maximize2 size={14} /> Enlarge QR
                </button>
              </div>
            ) : qrError || !ticket.qr_available ? (
              <div className="pass-qr-fallback">
                <QrCode size={48} className="qr-fallback-icon" />
                <p>QR image unavailable</p>
              </div>
            ) : (
              <div className="pass-qr-fallback">
                <QrCode size={48} className="qr-fallback-icon" />
                <p>No QR generated</p>
              </div>
            )}
            <small className="pass-qr-instructions">
              {isEligible
                ? 'Scan at venue entrance for check-in.'
                : 'This ticket is not eligible for admission.'}
            </small>
          </div>
        </div>
      </section>

      {/* Ticket Action Buttons (Hidden during printing) */}
      <div className="ticket-actions-bar no-print">
        {isEligible && (
          <button
            type="button"
            className="button button-primary"
            onClick={handleDownload}
            disabled={downloading}
          >
            <Download size={16} /> {downloading ? 'Preparing PDF…' : 'Download ticket PDF'}
          </button>
        )}
        <button type="button" className="button button-secondary" onClick={handlePrint}>
          <Printer size={16} /> Print ticket
        </button>
        <Link to={`/my-bookings/${ticket.booking_id}`} className="button button-secondary">
          View booking details
        </Link>
      </div>

      {/* QR Modal for enlarged gate check-in view */}
      {enlargeQr && qrUrl && (
        <div
          className="qr-modal-overlay no-print"
          role="dialog"
          aria-modal="true"
          aria-labelledby="qr-modal-title"
          onClick={() => setEnlargeQr(false)}
        >
          <div className="qr-modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="qr-modal-header">
              <h3 id="qr-modal-title">Ticket QR Code</h3>
              <button
                type="button"
                className="qr-modal-close"
                onClick={() => setEnlargeQr(false)}
                aria-label="Close enlarged QR"
              >
                <X size={20} />
              </button>
            </div>
            <div className="qr-modal-body">
              <img
                src={qrUrl}
                alt={`Enlarged QR code for ticket ${ticket.ticket_number}`}
                className="qr-modal-image"
              />
              <p className="qr-modal-meta">
                <strong>{ticket.event_name}</strong>
                <span>
                  Row {ticket.seat_row}, Seat {ticket.seat_number} · {ticket.tier_name}
                </span>
                <span>Ticket #{ticket.ticket_number}</span>
              </p>
            </div>
            <div className="qr-modal-footer">
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setEnlargeQr(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
