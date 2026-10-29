export interface EventRecord {
  id: number
  name: string
  venue: number
  venue_name: string
  description: string
  starts_at: string
  ends_at: string
}

export interface Venue {
  id: number
  name: string
  address: string
  city: string
}

export interface EventSeat {
  id: number
  event: number
  seat: number
  seat_row: string
  seat_number: number
  ticket_tier: number
  ticket_tier_name: string
  price: string
  availability_status: 'available' | 'held' | 'sold'
}

export interface BookingItem {
  id: number
  event_seat: number
  event_id: number
  event_name: string
  seat_row: string
  seat_number: number
  price: string
}

export type BookingStatus =
  | 'held'
  | 'payment_pending'
  | 'confirmed'
  | 'expired'
  | 'cancelled'
  | 'refunded'

export interface Booking {
  id: number
  status: BookingStatus
  total_amount: string
  created_at: string
  updated_at: string
  hold_expires_at: string | null
  items: BookingItem[]
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface User {
  id: number
  username: string
  email: string
}

export interface TokenPair {
  access: string
  refresh: string
}

export interface PaymentOrder {
  booking_id: number
  payment_id: number
  razorpay_order_id: string
  razorpay_key_id: string
  amount: number
  currency: string
}

export interface PaymentVerification {
  detail: string
  booking_id: number
  payment_id: number
  payment_status: string
  booking_status: BookingStatus
}
