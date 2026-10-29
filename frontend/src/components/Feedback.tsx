import { AlertCircle, CalendarDays, LoaderCircle, RotateCw } from 'lucide-react'
import type { ReactNode } from 'react'

export function LoadingState({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <LoaderCircle size={22} className="spin" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  )
}

export function SkeletonCards({ count = 3 }: { count?: number }) {
  return (
    <div className="event-grid" aria-label="Loading events" aria-busy="true">
      {Array.from({ length: count }, (_, index) => (
        <div className="event-card skeleton-card" key={index}>
          <div className="skeleton-poster" />
          <div className="skeleton-line wide" />
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
        </div>
      ))}
    </div>
  )
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div className="feedback-card error-card" role="alert">
      <span className="feedback-icon"><AlertCircle size={21} /></span>
      <div>
        <h2>We couldn’t load this</h2>
        <p>{message}</p>
        {onRetry && (
          <button className="button button-secondary button-small" onClick={onRetry}>
            <RotateCw size={15} /> Try again
          </button>
        )}
      </div>
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon"><CalendarDays size={23} /></span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  )
}
