# TicketFlow frontend

Responsive React + TypeScript frontend for the existing TicketFlow Django API. The frontend consumes the real API; it does not contain sample event records or simulated payment success.

## Requirements

- Node.js 20.19+ (Node 20 LTS recommended)
- npm
- TicketFlow backend configured and reachable
- A Razorpay test account for completing checkout

## Run locally on Windows

From the repository root, configure the Django `.env` using the root `.env.example`, then start Django:

```powershell
.\venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py runserver
```

In another PowerShell terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`). The Vite development server proxies `/api` requests to `http://127.0.0.1:8000`; set `VITE_DJANGO_ORIGIN` in `frontend/.env` if Django runs elsewhere.

## Environment and production

`VITE_API_BASE_URL` is optional in local development. Set it to the backend API root, including `/api`, when the built frontend is served separately. If the deployed frontend and Django API have different origins, configure Django CORS to allow only the frontend origin; CORS is not currently configured in this repository. Serving the frontend and API on the same origin avoids that requirement.

Razorpay’s public checkout key is returned by the authenticated payment-order API and used only when opening Checkout. The frontend has no Razorpay secret or webhook secret. Put `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` only in the Django environment, using test credentials for local testing.

```powershell
npm run build
npm run preview
npm test
```

## Routes

| Route | Purpose |
|---|---|
| `/` | Event discovery home, search, upcoming events |
| `/events` | Search, venue/date filters, backend sorting and pagination |
| `/events/:eventId` | Event details, venue and ticket price information |
| `/events/:eventId/seats` | Assigned-seat availability and selection (sign-in required) |
| `/login`, `/register` | JWT sign-in and account creation |
| `/checkout/:bookingId` | Booking review, hold timer, Razorpay Checkout and verification |
| `/booking-confirmation/:bookingId` | Backend booking/payment status |
| `/my-bookings`, `/my-bookings/:bookingId` | Authenticated booking list and detail |
| `/profile` | Read-only account details and sign-out |

## API integration inventory

The paths below are relative to the configured API root (`/api`). List endpoints use DRF page-number pagination: `count`, `next`, `previous`, and `results` (10 items per page).

| Feature | Method and endpoint | Request | Response and access |
|---|---|---|---|
| Health | `GET /health/` | — | `{status, service}`; public; not needed by UI |
| Event list/search | `GET /events/` | `page`, `search`, `venue`, `starts_after`, `starts_before`, `ordering` query parameters | Paginated event records; public. Search covers name, description, and venue name. Supported ordering: `name`, `starts_at`, `created_at` (optionally prefixed with `-`). |
| Event details | `GET /events/:id/` | — | Event fields: `id`, `name`, `venue`, `venue_name`, `description`, `starts_at`, `ends_at`; public |
| Venue list/details | `GET /venues/`, `GET /venues/:id/` | — | Paginated venues or `{id, name, address, city}`; public |
| Event seat availability | `GET /events/:eventId/seats/?page=N` | — | Paginated assigned seats with `seat_row`, `seat_number`, `ticket_tier_name`, `price`, and `availability_status`; public. The status field is added by this frontend integration and is `available`, `held`, or `sold`. |
| Register | `POST /auth/register/` | `{username, email, password}` | Created user fields; public. Password is write-only. |
| Obtain JWT | `POST /auth/token/` | `{username, password}` | `{access, refresh}`; public. Login uses username, not email. |
| Refresh JWT | `POST /auth/token/refresh/` | `{refresh}` | `{access}`; public. The client refreshes once after an API 401 and does not retry the same request repeatedly. |
| Current user | `GET /auth/me/` | — | `{id, username, email}`; JWT required |
| Create seat hold | `POST /bookings/holds/` | `{event_id, event_seat_ids}`; 1–10 unique event-seat IDs | Booking with authoritative total, items and `hold_expires_at`; JWT required. Hold lifetime is 10 minutes. `event_id` on booking items is also exposed for event links. |
| Booking history/detail | `GET /bookings/`, `GET /bookings/:id/` | `page` for list | Paginated booking records or one booking; JWT required. The API scopes both routes to the current user. |
| Create/reuse payment order | `POST /bookings/payments/create-order/` | `{booking_id}` | `{booking_id, payment_id, razorpay_order_id, razorpay_key_id, amount, currency}`; JWT required. Existing safe pending orders are reused; uncertain attempts are not silently recreated. |
| Verify payment | `POST /bookings/payments/verify/` | `{booking_id, razorpay_order_id, razorpay_payment_id, razorpay_signature}` | `{detail, booking_id, payment_id, payment_status, booking_status}`; JWT required. Confirmation is shown only when the backend returns `booking_status: confirmed`. |
| Razorpay webhook | `POST /bookings/payments/webhook/` | Provider webhook payload and signature headers | Provider processing response; public signature-verified endpoint. Called by Razorpay, not the browser. |
| Venue seat list | `GET /venues/:id/seats/` | `page` | Paginated physical venue seats; public; not needed because the event seat endpoint already includes event-specific prices and availability. |

## Authentication and payment notes

Access and refresh JWTs are kept in `sessionStorage` by one API/auth module. This is browser-accessible token storage and is **not equivalent to HttpOnly-cookie protection**. The access token is attached as a Bearer token; the refresh token is used only at the backend refresh endpoint. Passwords are never stored. Signing out clears both tokens.

The backend owns seat availability, booking totals, hold expiry and booking/payment status. The browser countdown uses the returned `hold_expires_at`, but the server revalidates the hold when creating a payment order. Checkout closing is not treated as payment success. The backend verification response and booking status remain authoritative, and the checkout page allows status refresh after an uncertain result.

## Backend-supported limits

- Events currently have no category or image fields, so the interface uses abstract neutral artwork rather than presenting arbitrary images as event data. Category filtering is not offered because no category API exists.
- Event-specific assigned seats and ticket prices are available; generic-admission quantity selection is not part of this backend model.
- No ticket, QR-code, ticket-download, cancellation, refund, email, or profile-edit API is exposed. These actions are not claimed or simulated in the frontend.
- The API does not expose a separate payment-history endpoint. Payment details are therefore not fabricated in booking views.
- Production CORS configuration is absent. Use a same-origin deployment or add a strict allowlist for the deployed frontend origin.

## Tests

Frontend tests mock API and Razorpay calls; they do not depend on a live provider:

```powershell
npm test
npm run build
```

Backend API regression tests for the additional availability and hold-expiry fields:

```powershell
cd ..
.\venv\Scripts\python.exe -m pytest events\test_seat_api.py bookings\test_api.py
```
