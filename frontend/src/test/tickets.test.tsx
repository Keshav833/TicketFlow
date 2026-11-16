import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import { AuthProvider } from '../auth/AuthProvider'
import { App } from '../App'
import { TicketDetailPage, TicketWalletPage } from '../pages/TicketPages'
import type { CustomerTicket, Paginated } from '../types'

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
    cancelBooking: vi.fn(),
    createPaymentOrder: vi.fn(),
    verifyPayment: vi.fn(),
    tickets: vi.fn(),
    ticket: vi.fn(),
    ticketQr: vi.fn(),
    downloadTicket: vi.fn(),
  },
}))

const sampleTicket: CustomerTicket = {
  id: 101,
  ticket_number: 'TF-TKT-98765',
  status: 'issued',
  issued_at: '2027-03-01T10:00:00Z',
  used_at: null,
  booking_id: 42,
  booking_status: 'confirmed',
  price: '750.00',
  event_id: 21,
  event_name: 'Starlight Symphony',
  event_starts_at: '2027-04-15T19:30:00Z',
  event_ends_at: '2027-04-15T22:00:00Z',
  venue_name: 'Royal Opera House',
  venue_city: 'Mumbai',
  seat_row: 'C',
  seat_number: 14,
  tier_name: 'VIP Stalls',
  qr_available: true,
}

const sampleUsedTicket: CustomerTicket = {
  ...sampleTicket,
  id: 102,
  ticket_number: 'TF-TKT-98766',
  status: 'used',
  used_at: '2027-04-15T19:25:00Z',
  seat_row: 'C',
  seat_number: 15,
}

const sampleCancelledTicket: CustomerTicket = {
  ...sampleTicket,
  id: 103,
  ticket_number: 'TF-TKT-98767',
  status: 'cancelled',
  booking_status: 'cancelled',
  seat_row: 'D',
  seat_number: 1,
}

const ticketPage = (results: CustomerTicket[]): Paginated<CustomerTicket> => ({
  count: results.length,
  next: null,
  previous: null,
  results,
})

function renderWithRouter(ui: React.ReactNode, initialEntry = '/') {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>
    </AuthProvider>,
  )
}

describe('Phase 2 – Customer Ticket Wallet UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    vi.mocked(api.currentUser).mockResolvedValue({
      data: { id: 1, username: 'customer1', email: 'customer@example.com' },
    } as never)
  })

  it('renders tickets in wallet with event, date, venue, seat, and status badge', async () => {
    vi.mocked(api.tickets).mockResolvedValue({
      data: ticketPage([sampleTicket, sampleUsedTicket]),
    } as never)

    renderWithRouter(<TicketWalletPage />, '/my-tickets')

    expect(await screen.findByRole('heading', { name: 'My tickets' })).toBeInTheDocument()
    expect(screen.getAllByText('Starlight Symphony').length).toBe(2)
    expect(screen.getByText('TICKET #TF-TKT-98765')).toBeInTheDocument()
    expect(screen.getAllByText('Royal Opera House, Mumbai').length).toBe(2)
    expect(screen.getByText('Row C, Seat 14')).toBeInTheDocument()
    expect(screen.getAllByText('VIP Stalls').length).toBe(2)
    expect(screen.getAllByText('TF-42').length).toBe(2)
    expect(screen.getByText('Confirmed')).toBeInTheDocument()
    expect(screen.getByText('Used')).toBeInTheDocument()
    expect(api.tickets).toHaveBeenCalledWith({ params: { page: 1 } })
  })

  it('filters tickets by status chips in wallet', async () => {
    vi.mocked(api.tickets).mockResolvedValue({
      data: ticketPage([sampleTicket, sampleUsedTicket, sampleCancelledTicket]),
    } as never)

    renderWithRouter(<TicketWalletPage />, '/my-tickets')

    expect(await screen.findByText('TICKET #TF-TKT-98765')).toBeInTheDocument()
    expect(screen.getByText('TICKET #TF-TKT-98766')).toBeInTheDocument()
    expect(screen.getByText('TICKET #TF-TKT-98767')).toBeInTheDocument()

    // Filter to Used tickets
    const usedFilter = screen.getByRole('button', { name: /used/i })
    await userEvent.click(usedFilter)

    expect(screen.queryByText('TICKET #TF-TKT-98765')).not.toBeInTheDocument()
    expect(screen.getByText('TICKET #TF-TKT-98766')).toBeInTheDocument()
    expect(screen.queryByText('TICKET #TF-TKT-98767')).not.toBeInTheDocument()
  })

  it('renders an empty state when customer has no confirmed tickets', async () => {
    vi.mocked(api.tickets).mockResolvedValue({
      data: ticketPage([]),
    } as never)

    renderWithRouter(<TicketWalletPage />, '/my-tickets')

    expect(await screen.findByText('Your ticket wallet is empty')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /explore upcoming events/i })).toHaveAttribute(
      'href',
      '/events',
    )
  })

  it('handles API error state and retries', async () => {
    vi.mocked(api.tickets).mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: 'Service temporarily down.' } },
    } as never)
    vi.mocked(api.tickets).mockResolvedValueOnce({
      data: ticketPage([sampleTicket]),
    } as never)

    renderWithRouter(<TicketWalletPage />, '/my-tickets')

    expect(await screen.findByRole('alert')).toHaveTextContent('Service temporarily down.')
    const retryBtn = screen.getByRole('button', { name: /try again/i })
    await userEvent.click(retryBtn)

    expect(await screen.findByText('Starlight Symphony')).toBeInTheDocument()
    expect(api.tickets).toHaveBeenCalledTimes(2)
  })

  it('renders ticket details and displays the real QR code from the backend', async () => {
    vi.mocked(api.ticket).mockResolvedValue({ data: sampleTicket } as never)
    const mockBlob = new Blob(['mock-qr-bytes'], { type: 'image/png' })
    vi.mocked(api.ticketQr).mockResolvedValue({ data: mockBlob } as never)

    const createObjectUrlSpy = vi
      .spyOn(window.URL, 'createObjectURL')
      .mockReturnValue('blob:http://localhost/mock-qr-blob-url')
    const revokeObjectUrlSpy = vi.spyOn(window.URL, 'revokeObjectURL').mockImplementation(() => {})

    renderWithRouter(
      <Routes>
        <Route path="/my-tickets/:ticketId" element={<TicketDetailPage />} />
      </Routes>,
      '/my-tickets/101',
    )

    expect(await screen.findByRole('heading', { level: 1, name: 'Starlight Symphony' })).toBeInTheDocument()
    expect(screen.getByText('Royal Opera House')).toBeInTheDocument()
    expect(screen.getByText('VIP Stalls')).toBeInTheDocument()
    expect(screen.getByText('TF-TKT-98765')).toBeInTheDocument()
    expect(api.ticket).toHaveBeenCalledWith(101)
    expect(api.ticketQr).toHaveBeenCalledWith(101)

    // Verify QR code image is rendered with the object URL
    const qrImage = await screen.findByAltText('QR code for ticket TF-TKT-98765')
    expect(qrImage).toHaveAttribute('src', 'blob:http://localhost/mock-qr-blob-url')

    createObjectUrlSpy.mockRestore()
    revokeObjectUrlSpy.mockRestore()
  })

  it('opens and closes the enlarged QR modal', async () => {
    vi.mocked(api.ticket).mockResolvedValue({ data: sampleTicket } as never)
    const mockBlob = new Blob(['mock-qr-bytes'], { type: 'image/png' })
    vi.mocked(api.ticketQr).mockResolvedValue({ data: mockBlob } as never)

    vi.spyOn(window.URL, 'createObjectURL').mockReturnValue('blob:http://localhost/mock-qr-blob-url')
    vi.spyOn(window.URL, 'revokeObjectURL').mockImplementation(() => {})

    renderWithRouter(
      <Routes>
        <Route path="/my-tickets/:ticketId" element={<TicketDetailPage />} />
      </Routes>,
      '/my-tickets/101',
    )

    const enlargeBtn = await screen.findByRole('button', { name: /enlarge qr/i })
    await userEvent.click(enlargeBtn)

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Ticket QR Code')).toBeInTheDocument()

    const closeBtn = screen.getByRole('button', { name: /close enlarged qr/i })
    await userEvent.click(closeBtn)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('downloads the ticket PDF via blob response', async () => {
    vi.mocked(api.ticket).mockResolvedValue({ data: sampleTicket } as never)
    const mockPdfBlob = new Blob(['mock-pdf-bytes'], { type: 'application/pdf' })
    vi.mocked(api.ticketQr).mockResolvedValue({ data: new Blob() } as never)
    vi.mocked(api.downloadTicket).mockResolvedValue({ data: mockPdfBlob } as never)

    vi.spyOn(window.URL, 'createObjectURL').mockReturnValue('blob:http://localhost/mock-pdf-blob')
    vi.spyOn(window.URL, 'revokeObjectURL').mockImplementation(() => {})

    renderWithRouter(
      <Routes>
        <Route path="/my-tickets/:ticketId" element={<TicketDetailPage />} />
      </Routes>,
      '/my-tickets/101',
    )

    const downloadBtn = await screen.findByRole('button', { name: /download ticket pdf/i })
    await userEvent.click(downloadBtn)

    expect(api.downloadTicket).toHaveBeenCalledWith(101)
  })

  it('triggers window.print when print button is clicked', async () => {
    vi.mocked(api.ticket).mockResolvedValue({ data: sampleTicket } as never)
    vi.mocked(api.ticketQr).mockResolvedValue({ data: new Blob() } as never)
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})

    renderWithRouter(
      <Routes>
        <Route path="/my-tickets/:ticketId" element={<TicketDetailPage />} />
      </Routes>,
      '/my-tickets/101',
    )

    const printBtn = await screen.findByRole('button', { name: /print ticket/i })
    await userEvent.click(printBtn)

    expect(printSpy).toHaveBeenCalled()
    printSpy.mockRestore()
  })

  it('protects the /my-tickets route when user is unauthenticated', async () => {
    sessionStorage.clear()
    vi.mocked(api.currentUser).mockRejectedValueOnce(new Error('Unauthenticated'))

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/my-tickets']}>
          <App />
        </MemoryRouter>
      </AuthProvider>,
    )

    expect(await screen.findByRole('heading', { name: 'Sign in to TicketFlow' })).toBeInTheDocument()
  })
})
