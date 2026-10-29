import type { AxiosRequestConfig } from 'axios'
import { apiClient } from './client'
import type {
  Booking,
  EventRecord,
  EventSeat,
  Paginated,
  PaymentOrder,
  PaymentVerification,
  TokenPair,
  User,
  Venue,
} from '../types'

export interface EventQuery {
  page?: number
  search?: string
  venue?: number
  starts_after?: string
  starts_before?: string
  ordering?: 'starts_at' | '-starts_at' | 'name' | '-name'
}

export const api = {
  login: (username: string, password: string) =>
    apiClient.post<TokenPair>('/auth/token/', { username, password }),
  register: (data: { username: string; email: string; password: string }) =>
    apiClient.post<User>('/auth/register/', data),
  currentUser: () => apiClient.get<User>('/auth/me/'),
  listEvents: (params: EventQuery, config?: AxiosRequestConfig) =>
    apiClient.get<Paginated<EventRecord>>('/events/', { ...config, params }),
  event: (id: number, config?: AxiosRequestConfig) =>
    apiClient.get<EventRecord>(`/events/${id}/`, config),
  listVenues: (config?: AxiosRequestConfig) =>
    apiClient.get<Paginated<Venue>>('/venues/', config),
  venue: (id: number, config?: AxiosRequestConfig) =>
    apiClient.get<Venue>(`/venues/${id}/`, config),
  eventSeats: (eventId: number, page: number, config?: AxiosRequestConfig) =>
    apiClient.get<Paginated<EventSeat>>(`/events/${eventId}/seats/`, {
      ...config,
      params: { page },
    }),
  createHold: (eventId: number, eventSeatIds: number[]) =>
    apiClient.post<Booking>('/bookings/holds/', {
      event_id: eventId,
      event_seat_ids: eventSeatIds,
    }),
  bookings: (config?: AxiosRequestConfig) =>
    apiClient.get<Paginated<Booking>>('/bookings/', config),
  booking: (id: number, config?: AxiosRequestConfig) =>
    apiClient.get<Booking>(`/bookings/${id}/`, config),
  createPaymentOrder: (bookingId: number) =>
    apiClient.post<PaymentOrder>('/bookings/payments/create-order/', {
      booking_id: bookingId,
    }),
  verifyPayment: (payload: {
    booking_id: number
    razorpay_order_id: string
    razorpay_payment_id: string
    razorpay_signature: string
  }) =>
    apiClient.post<PaymentVerification>('/bookings/payments/verify/', payload),
}
