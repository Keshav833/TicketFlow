import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { Booking, EventRecord, EventSeat, Paginated } from '../types'
import { AuthProvider } from '../auth/AuthProvider'
import { App } from '../App'
import { AuthPage } from '../pages/AuthPage'
import { BookingHistoryPage, CheckoutPage } from '../pages/BookingPages'
import { EventsPage } from '../pages/EventsPage'
import { HomePage } from '../pages/HomePage'
import { SeatSelectionPage } from '../pages/SeatSelectionPage'

vi.mock('../api', () => ({
  api: {
    login: vi.fn(),
    register: vi.fn(),
    currentUser: vi.fn(),
    listEvents: vi.fn(),
    event: vi.fn(),
    listVenues: vi.fn(),
    venue: vi.fn(),
    eventSeats: vi.fn(),
    createHold: vi.fn(),
    bookings: vi.fn(),
    booking: vi.fn(),
    createPaymentOrder: vi.fn(),
    verifyPayment: vi.fn(),
  },
}))

const sampleEvent: EventRecord = {
  id: 21,
  name: 'Evening of Ideas',
  venue: 3,
  venue_name: 'The Grand Hall',
  description: 'Talks, music, and good company.',
  starts_at: '2027-03-10T18:00:00Z',
  ends_at: '2027-03-10T21:00:00Z',
}

const sampleBooking = (expiresAt = new Date(Date.now() + 300_000).toISOString()): Booking => ({
  id: 42,
  status: 'held',
  total_amount: '500.00',
  created_at: '2027-03-01T10:00:00Z',
  updated_at: '2027-03-01T10:00:00Z',
  hold_expires_at: expiresAt,
  items: [{
    id: 7,
    event_seat: 11,
    event_id: 21,
    event_name: 'Evening of Ideas',
    seat_row: 'A',
    seat_number: 1,
    price: '500.00',
  }],
})

const eventPage = (results: EventRecord[]): Paginated<EventRecord> => ({
  count: results.length,
  next: null,
  previous: null,
  results,
})

const seatPage = (results: EventSeat[]): Paginated<EventSeat> => ({
  count: results.length,
  next: null,
  previous: null,
  results,
})

function renderRouter(ui: React.ReactNode, initialEntry = '/') {
  return render(<MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>)
}

describe('TicketFlow pages', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    vi.mocked(api.currentUser).mockResolvedValue({
      data: { id: 1, username: 'testuser', email: 'test@example.com' },
    } as never)
    vi.mocked(api.listEvents).mockResolvedValue({ data: eventPage([]) } as never)
    vi.mocked(api.listVenues).mockResolvedValue({
      data: { count: 0, next: null, previous: null, results: [] },
    } as never)
  })

  it('renders a polished empty home state when the API has no events', async () => {
    renderRouter(<HomePage />)
    expect(await screen.findByText('The calendar is taking a breather')).toBeInTheDocument()
    expect(api.listEvents).toHaveBeenCalledWith(
      expect.objectContaining({ ordering: 'starts_at', starts_after: expect.any(String) }),
    )
  })

  it('shows an event API failure and retries the request', async () => {
    vi.mocked(api.listEvents)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ data: eventPage([]) } as never)
    renderRouter(<HomePage />)
    expect(await screen.findByText('We couldn’t load this')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))
    await waitFor(() => expect(api.listEvents).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('The calendar is taking a breather')).toBeInTheDocument()
  })

  it('enforces required login fields and displays backend authentication errors', async () => {
    vi.mocked(api.login).mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: 'Invalid username or password.' } },
    } as never)
    renderRouter(
      <AuthProvider><AuthPage mode="login" /></AuthProvider>,
      '/login',
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(api.login).not.toHaveBeenCalled()
    await user.type(screen.getByLabelText('Username'), 'testuser')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
  })

  it('registers using the supported username, email, and password fields', async () => {
    vi.mocked(api.register).mockResolvedValueOnce({ data: { id: 5 } } as never)
    renderRouter(<AuthProvider><AuthPage mode="register" /></AuthProvider>, '/register')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Username'), 'newuser')
    await user.type(screen.getByLabelText('Email address'), 'new@example.com')
    await user.type(screen.getByLabelText('Password'), 'securepass123')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText(/your account is ready/i)).toBeInTheDocument()
    expect(api.register).toHaveBeenCalledWith({
      username: 'newuser',
      email: 'new@example.com',
      password: 'securepass123',
    })
  })

  it('sends event search to the backend rather than filtering a local dataset', async () => {
    vi.mocked(api.listEvents).mockResolvedValue({
      data: eventPage([sampleEvent]),
    } as never)
    renderRouter(<EventsPage />, '/events')
    await screen.findByText('Evening of Ideas')
    await userEvent.type(screen.getByLabelText('Search'), 'ideas')
    await userEvent.click(screen.getByRole('button', { name: 'Search events' }))
    await waitFor(() => {
      expect(api.listEvents).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: 'ideas' }),
        expect.anything(),
      )
    })
  })

  it('disables held seats and creates one hold for the selected available seats', async () => {
    const seats: EventSeat[] = [
      {
        id: 11, event: 21, seat: 1, seat_row: 'A', seat_number: 1,
        ticket_tier: 2, ticket_tier_name: 'Standard', price: '500.00',
        availability_status: 'available',
      },
      {
        id: 12, event: 21, seat: 2, seat_row: 'A', seat_number: 2,
        ticket_tier: 2, ticket_tier_name: 'Standard', price: '500.00',
        availability_status: 'held',
      },
    ]
    vi.mocked(api.event).mockResolvedValue({ data: sampleEvent } as never)
    vi.mocked(api.eventSeats).mockResolvedValue({ data: seatPage(seats) } as never)
    vi.mocked(api.createHold).mockResolvedValue({ data: sampleBooking() } as never)

    render(
      <MemoryRouter initialEntries={['/events/21/seats']}>
        <Routes>
          <Route path="/events/:eventId/seats" element={<SeatSelectionPage />} />
          <Route path="/checkout/:bookingId" element={<p>Checkout for booking 42</p>} />
        </Routes>
      </MemoryRouter>,
    )
    const available = await screen.findByRole('button', { name: /row a, seat 1/i })
    expect(screen.getByRole('button', { name: /row a, seat 2/i })).toBeDisabled()
    await userEvent.click(available)
    await userEvent.click(screen.getByRole('button', { name: /hold & continue/i }))
    expect(await screen.findByText('Checkout for booking 42')).toBeInTheDocument()
    expect(api.createHold).toHaveBeenCalledTimes(1)
    expect(api.createHold).toHaveBeenCalledWith(21, [11])
  })

  it('blocks checkout after the backend-provided hold expiry', async () => {
    vi.mocked(api.booking).mockResolvedValue({
      data: sampleBooking(new Date(Date.now() - 10_000).toISOString()),
    } as never)
    vi.mocked(api.event).mockResolvedValue({ data: sampleEvent } as never)
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/checkout/42']}>
          <Routes><Route path="/checkout/:bookingId" element={<CheckoutPage />} /></Routes>
        </MemoryRouter>
      </AuthProvider>,
    )
    expect(await screen.findByText('Your seat hold has expired')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /continue to secure payment/i })).toBeDisabled()
    expect(api.createPaymentOrder).not.toHaveBeenCalled()
  })

  it('only shows booking confirmation after backend payment verification succeeds', async () => {
    vi.mocked(api.booking).mockResolvedValue({ data: sampleBooking() } as never)
    vi.mocked(api.event).mockResolvedValue({ data: sampleEvent } as never)
    vi.mocked(api.createPaymentOrder).mockResolvedValue({
      data: {
        booking_id: 42,
        payment_id: 9,
        razorpay_order_id: 'order_test',
        razorpay_key_id: 'rzp_test_public',
        amount: 50000,
        currency: 'INR',
      },
    } as never)
    vi.mocked(api.verifyPayment).mockResolvedValue({
      data: {
        detail: 'Payment verified successfully.',
        booking_id: 42,
        payment_id: 9,
        payment_status: 'succeeded',
        booking_status: 'confirmed',
      },
    } as never)

    class MockCheckout {
      constructor(private readonly options: RazorpayCheckoutOptions) {}
      on() {}
      open() {
        void this.options.handler({
          razorpay_order_id: 'order_test',
          razorpay_payment_id: 'pay_test',
          razorpay_signature: 'signature_test',
        })
      }
    }
    window.Razorpay = MockCheckout

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/checkout/42']}>
          <Routes>
            <Route path="/checkout/:bookingId" element={<CheckoutPage />} />
            <Route path="/booking-confirmation/:bookingId" element={<p>Verified booking confirmation</p>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /continue to secure payment/i }))
    expect(await screen.findByText('Verified booking confirmation')).toBeInTheDocument()
    expect(api.verifyPayment).toHaveBeenCalledWith({
      booking_id: 42,
      razorpay_order_id: 'order_test',
      razorpay_payment_id: 'pay_test',
      razorpay_signature: 'signature_test',
    })
  })

  it('keeps an uncertain payment pending and allows status recovery', async () => {
    const pendingBooking: Booking = { ...sampleBooking(), status: 'payment_pending' }
    vi.mocked(api.booking).mockResolvedValue({ data: pendingBooking } as never)
    vi.mocked(api.event).mockResolvedValue({ data: sampleEvent } as never)
    vi.mocked(api.createPaymentOrder).mockResolvedValue({
      data: {
        booking_id: 42,
        payment_id: 9,
        razorpay_order_id: 'order_test',
        razorpay_key_id: 'rzp_test_public',
        amount: 50000,
        currency: 'INR',
      },
    } as never)
    vi.mocked(api.verifyPayment).mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: 'Payment is not captured yet.' } },
    } as never)

    class MockCheckout {
      constructor(private readonly options: RazorpayCheckoutOptions) {}
      on() {}
      open() {
        void this.options.handler({
          razorpay_order_id: 'order_test',
          razorpay_payment_id: 'pay_test',
          razorpay_signature: 'signature_test',
        })
      }
    }
    window.Razorpay = MockCheckout

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/checkout/42']}>
          <Routes><Route path="/checkout/:bookingId" element={<CheckoutPage />} /></Routes>
        </MemoryRouter>
      </AuthProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /continue secure payment/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Payment is not captured yet.')
    await userEvent.click(screen.getByRole('button', { name: /refresh booking status/i }))
    expect(await screen.findByText(/current booking status: payment pending/i)).toBeInTheDocument()
    expect(api.booking).toHaveBeenCalledTimes(2)
  })

  it('renders only the authenticated booking-history response', async () => {
    vi.mocked(api.bookings).mockResolvedValue({
      data: {
        count: 1,
        next: null,
        previous: null,
        results: [{ ...sampleBooking(), status: 'confirmed' }],
      },
    } as never)
    renderRouter(<BookingHistoryPage />, '/my-bookings')
    expect(await screen.findByText('Evening of Ideas')).toBeInTheDocument()
    expect(screen.getByText('Confirmed')).toBeInTheDocument()
    expect(api.bookings).toHaveBeenCalledWith({ params: { page: 1 } })
  })

  it('shows protected routes behind sign-in when the session is missing', async () => {
    renderRouter(
      <AuthProvider><App /></AuthProvider>,
      '/my-bookings',
    )
    expect(await screen.findByRole('heading', { name: 'Sign in to TicketFlow' })).toBeInTheDocument()
  })
})
