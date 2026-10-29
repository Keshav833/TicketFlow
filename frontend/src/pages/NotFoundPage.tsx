import { ArrowLeft, SearchX } from 'lucide-react'
import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="content-wrap page-section not-found">
      <span className="not-found-icon"><SearchX size={29} /></span>
      <p className="eyebrow">404 · WRONG TURN</p>
      <h1>This page isn’t on the guest list.</h1>
      <p>The link may be outdated, or the page may have moved. Let’s find something happening.</p>
      <Link to="/" className="button button-primary"><ArrowLeft size={16} /> Back to TicketFlow</Link>
    </div>
  )
}
