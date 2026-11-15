
<p align="center">
  <img
    src="https://plain-apac-prod-public.komododecks.com/202610/15/qU1sKyfhRGHTLUL4OiWk/image.png"
    alt="TicketFlow Banner"
    width="100%"
     style="
      border-radius: 16px;
      border: 2px solid #cbd5e1;
      box-shadow:
        0 2px 0 #94a3b8,
        0 1px 3px rgba(0, 0, 0, 0.18);
    "
  />
</p>

**Django-based Event Ticket Booking & Payment Service**

TicketFlow is a backend service for booking event tickets. It handles seat holds with expiry, concurrent bookings without double-booking, Razorpay payments (test mode) with idempotent webhooks, and background processing with Celery. It is built to demonstrate scalability, concurrency handling, and clean backend design.

---

##  Goals

- Build a real-world backend project from scratch
- Focus on scalability, concurrency, and clean design
- Use industry-relevant tools (Django, Postgres, Redis, Celery, etc.)
- Have a strong project for resume and interviews

---

##  Key Features

- Event & seat management
- Seat holds with 10-minute expiry
- Booking state machine
- Razorpay payments (test mode)
- Idempotent webhook handling
- Background jobs (Celery)
- JWT auth + rate limiting
- API documentation (OpenAPI / Swagger)
- Tests, Docker, CI/CD
- Load testing & performance metrics

---

##  Tech Stack

| Area | Technology |
|---|---|
| Framework | Django + Django REST Framework |
| Database | PostgreSQL |
| Cache / Broker | Redis |
| Async jobs | Celery (worker + beat) |
| Payments | Razorpay (test mode) |
| Auth | JWT |
| Containerization | Docker, Docker Compose |
| Testing | pytest |
| CI/CD | GitHub Actions |
| Load testing | Locust / k6 |
| API docs | OpenAPI |

---

##  Architecture
<p align="center">
  <img
    src="https://plain-apac-prod-public.komododecks.com/202610/15/iAFPq6FhuQ0cdGWl0fRT/image.png"
    alt="TicketFlow System Architecture"
  />
</p>


##  Booking Flow & State Machine

```
held ──▶ payment_pending ──▶ confirmed
  │
  └──▶ expired / cancelled / refunded
```

1. User selects seats → a **hold** is created (10 min expiry).
2. A booking is created and a Razorpay order is generated.
3. Payment is verified (signature check) and the booking moves to `confirmed`.
4. Webhooks update booking state idempotently (duplicates are ignored).
5. Celery sends the confirmation email and generates the ticket (PDF/QR).
6. Unpaid holds are released by the expiry job.

---

##  Folder Structure

```
ticketflow/
├── manage.py
├── accounts/
├── bookings/
├── config/
├── core/
├── events/
├── users/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── README.md
└── requirements.txt
```

---

##  Getting Started

### Run the backend with Docker Compose

Prerequisites: Docker Desktop (or Docker Engine) with the Compose v2 plugin.
The Compose stack is intended for local development; Django uses `runserver`,
which is not a production application server.

From the repository root, create a local environment file only if you do not
already have one. Keep `.env` private and replace the sample secret and
password before using the stack:

```cmd
if not exist .env copy .env.example .env
```

Build and start PostgreSQL, Redis, Django, the Celery worker, and Celery Beat:

```cmd
docker compose up --build -d
docker compose ps
```

The web container applies migrations before starting. To apply migrations
manually after model changes:

```cmd
docker compose exec web python manage.py migrate
```

Create an administrator:

```cmd
docker compose exec web python manage.py createsuperuser
```

Useful operations:

```cmd
docker compose logs -f web worker beat db redis
docker compose exec web pytest
docker compose down
```

`docker compose down` stops and removes the containers but preserves named
volumes. The PostgreSQL database is persisted in the `postgres_data` volume;
Redis, uploaded media, and Celery Beat's scheduler state also use named
volumes. To permanently delete all persisted stack data, use
`docker compose down -v`.

Run exactly one `beat` service instance; scaling it can schedule duplicate
periodic tasks. Check service health with `docker compose ps`; worker and Beat
logs also show Celery broker connection and scheduler activity.

- API docs (Swagger): `http://localhost:8000/api/docs/`
- Admin: `http://localhost:8000/admin/`

Compose overrides `DB_HOST` to `db` and Redis URLs to `redis`, so the
containers connect through the Compose network while local settings continue
to use the host names in `.env`. Redis database 0 remains the Celery broker,
database 1 the result backend, and database 2 Django's cache. Configure
Razorpay test credentials and SMTP values in `.env` when those integrations
are needed; email uses the console backend by default.

### Frontend

The responsive React application is in [`frontend/`](./frontend/README.md). Start Django as above, then in a second PowerShell terminal run:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

The Vite development server proxies API calls to Django at `http://127.0.0.1:8000`. See the frontend README for the API inventory, supported backend features, test commands, and production configuration.

### Running tests

```bash
docker compose exec web pytest
```

## Load testing

The optional Locust workload is read-only and exercises public event listings,
event details, and per-event seat availability. It does not create bookings,
holds, or payments. It defaults to localhost; non-local targets require
`LOCUST_ALLOW_NONLOCAL=true`. Run it only against a local or staging
environment you own, never production.

`THROTTLE_ENABLED` defaults to `1`. Set it to `0` in the **server terminal**
before starting Django to disable global DRF throttling and the project's
explicit `SafeScopedRateThrottle` views. When enabled, Locust records HTTP 429s
as successful requests in separate `429 rate-limited ...` statistics; other
non-200 responses remain failures. Set the same variable in the Locust
terminal so its stats reflect the server's mode.

The cache-reset command clears Django's entire default cache, including both
DRF throttle counters and event response caches. In this configuration that
is Redis database 2, separate from Celery broker/result databases.

Install the optional dependency once:

```cmd
venv\Scripts\python.exe -m pip install -r requirements-load.txt
if not exist loadtest-results mkdir loadtest-results
```

### Baseline unthrottled run (two Command Prompt terminals)

In the **SERVER terminal**, from the repository root:

```cmd
set THROTTLE_ENABLED=0
venv\Scripts\python.exe manage.py clear_throttle_cache
venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

In the **LOCUST terminal**, from the repository root, verify 200 requests
first. Clear cache once more after verification so the run starts with an empty
cache:

```cmd
set THROTTLE_ENABLED=0
set LOCUST_EVENT_ID=1
venv\Scripts\python.exe loadtest\verify_throttle.py --count 200
venv\Scripts\python.exe manage.py clear_throttle_cache
venv\Scripts\python.exe -m locust -f loadtest\locustfile.py --host http://127.0.0.1:8000 --headless -u 20 -r 2 -t 2m --csv=loadtest-results\baseline-unthrottled --html=loadtest-results\baseline-unthrottled.html
```

The verification should report 200 responses with zero 429s. The cache
clearing command may be run from the Locust terminal; it clears the shared
server cache.

### Throttled run (two Command Prompt terminals)

Stop the previous server with Ctrl+C. In the **SERVER terminal**:

```cmd
set THROTTLE_ENABLED=1
venv\Scripts\python.exe manage.py clear_throttle_cache
venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

In the **LOCUST terminal**, verify the throttled behavior, then clear the
counters again before starting Locust:

```cmd
set THROTTLE_ENABLED=1
set LOCUST_EVENT_ID=1
venv\Scripts\python.exe loadtest\verify_throttle.py --count 200
venv\Scripts\python.exe manage.py clear_throttle_cache
venv\Scripts\python.exe -m locust -f loadtest\locustfile.py --host http://127.0.0.1:8000 --headless -u 20 -r 2 -t 2m --csv=loadtest-results\throttled --html=loadtest-results\throttled.html
```

With the default rates, the verifier should show 429s after the configured
limit is reached. Locust separates these expected 429s from actual request
failures.

Locust reports throughput, response-time percentiles (including p95), and
endpoint-level statistics. Its CSV and HTML reports are stored under
`loadtest-results`. For PostgreSQL sampling, start this command in another
terminal for each run:

```cmd
venv\Scripts\python.exe loadtest\db_metrics.py --duration 130 --interval 5 > loadtest-results\db-metrics.csv
```

Those counters are database-wide and include concurrent activity; they
indicate database activity but are not per-request query latency. For
query-level timing, enable PostgreSQL `pg_stat_statements` in the test
environment.

The verification script sends GET requests only:
`venv\Scripts\python.exe loadtest\verify_throttle.py --count 200`. Record the
machine/DB configuration, user count, spawn rate, duration, failure rate,
requests/sec, p95, and database metrics with the results. Generated
`loadtest-results` files are local test output and should not be committed.

## Redis response caching

TicketFlow uses Django's cache framework with the existing Redis service to
reduce repeated database work on public event browsing. Celery continues to
use Redis database 0 as its broker and database 1 as its result backend;
Django caching uses database 2. Set `REDIS_URL` to the Redis connection URL
(for example, `redis://localhost:6379`). The same URL is used for all three
Redis databases, and credentials should be supplied through the environment,
not committed to source control.

The cached endpoints are:

| Endpoint | Cached data | Default lifetime |
|---|---|---:|
| `GET /api/events/` | Serialized listing, including pagination metadata | 300 seconds |
| `GET /api/events/<id>/` | Serialized event detail | 300 seconds |
| `GET /api/events/<id>/seats/` | Serialized seat availability response | 20 seconds |

Listing keys include a hash of the complete query string and the requesting
user identity, so searches, filters, ordering, pages, and users do not share
responses. Seat availability keys are specific to the event, query string,
and requester. Cache values contain serialized response data, not QuerySets
or model instances.

Configure lifetimes with `EVENT_LIST_CACHE_TTL` and
`SEAT_AVAILABILITY_CACHE_TTL`. The default Redis cache connection and socket
timeouts are one second and can be adjusted with `REDIS_CACHE_CONNECT_TIMEOUT`
and `REDIS_CACHE_TIMEOUT`; `REDIS_CACHE_MAX_CONNECTIONS` defaults to 100.
During tests, Django uses an isolated in-memory cache, so tests do not require
a running Redis container.

Event listing/detail cache versions are advanced after an event is created,
updated, or deleted, or its venue changes. Seat-availability versions are
advanced after event seating, seat configuration, or ticket-tier changes;
when a hold is created, changed, deleted, or expires; and when a booking's
confirmation changes seat availability. Versioned keys make old responses
unreachable after invalidation and prevent an in-flight older read from
repopulating the current version.

Redis is only a performance optimization. If a cache operation fails, the
request falls back to the database and logs the cache failure. Seat holds
continue to validate availability against PostgreSQL inside the existing
transaction and row locks; cached availability is never used to authorize a
booking.

Request flow: a read checks Django's cache first; on a miss, TicketFlow reads
and serializes from PostgreSQL, then caches that response. A committed
booking/seat/event change advances the relevant cache version. If Redis is
unavailable, the same request is served from PostgreSQL without relying on
the cache.

Run the caching tests with:

```bash
pytest events/test_cache.py
```

## Admin dashboard and operations

The Django admin at `/admin/` is for staff users. Booking, payment, hold,
ticket, webhook-event, and email-delivery records are available for inspection.
Outbox events are also searchable and read-only; raw payload and error details
are not shown. Booking, payment, ticket, and hold state is read-only in admin;
changes must go through the application flows. Ticket verification tokens and
webhook signatures are not displayed.

The staff-only statistics endpoint is `GET /api/admin/dashboard/stats/`.
It reports booking, payment, ticket, and event counts, along with total,
today, and this-month successful-payment revenue. Revenue includes only
successful payments attached to confirmed bookings. Today/month totals use the
payment's `updated_at` timestamp as the available proxy for when payment
succeeded, so later payment updates can affect the period in which it appears.
Events are considered upcoming when `starts_at` is in the future.

Application logs are written at INFO level to the console and rotating
`logs/ticketflow.log`; ERROR-level records are also written to
`logs/errors.log`. Files rotate at 5 MB with five backups. Unexpected API
exceptions keep the established error response behavior and are logged by
exception type without returning internal details to the client. Unexpected
API exceptions return HTTP 500 with the same response envelope and a generic
message. Booking status and hold lifecycle logs are emitted after their
database transactions commit. Never add credentials, payment signatures,
JWTs, or webhook payloads to log messages.

Run the dashboard and admin tests with:

```bash
pytest bookings/tests/test_dashboard_admin.py bookings/tests/test_exceptions.py
```

## API rate limits and security

DRF's `ScopedRateThrottle` uses Django's configured default cache. In
production, that is Redis database 2 (shared with response caching); tests use
an isolated in-memory cache. Authenticated requests are identified by user ID,
while anonymous requests are identified by client IP. `DRF_NUM_PROXIES`
defaults to `0`, so arbitrary `X-Forwarded-For` values are not trusted. Set it
to the number of trusted, header-sanitizing proxies only when the deployment
proxy overwrites forwarded-client headers.

Throttle scopes and default limits are configurable through environment
variables:

| Scope | Default | Configuration |
|---|---:|---|
| Login | 5/minute | `THROTTLE_LOGIN_RATE` |
| Registration | 5/hour | `THROTTLE_REGISTRATION_RATE` |
| Token refresh | 30/minute | `THROTTLE_AUTH_REFRESH_RATE` |
| Event and venue browsing | 100/minute | `THROTTLE_EVENT_BROWSING_RATE` |
| Seat availability | 60/minute | `THROTTLE_SEAT_AVAILABILITY_RATE` |
| Booking reads | 60/minute | `THROTTLE_BOOKING_READ_RATE` |
| Seat holds | 10/minute | `THROTTLE_HOLD_CREATE_RATE` |
| Payment order creation | 5/minute | `THROTTLE_PAYMENT_ORDER_RATE` |
| Payment verification | 10/minute | `THROTTLE_PAYMENT_VERIFY_RATE` |
| Staff check-in | 10/minute | `THROTTLE_TICKET_CHECKIN_RATE` |

Razorpay webhooks are intentionally excluded from generic throttling so
provider retries are not blocked; webhook signatures and event-idempotency
checks remain required.

Events, venues, seat availability, health, registration, login, refresh, and
the signed payment webhook are public. Booking listing/detail, seat holds,
payment order creation, and payment verification require JWT authentication.
Bookings are filtered by their owner and payment services check booking
ownership. Ticket check-in requires an authenticated staff user; there is no
public ticket lookup endpoint.

Input validation uses explicit DRF serializer fields. Registration requires a
valid email and checks passwords against Django's configured validators.
Hold creation rejects duplicate or cross-event seat IDs and limits a booking
to ten seats. Payment endpoints validate identifiers and derive price/currency
from server-side records/provider verification, not frontend-supplied amounts.
Event search is limited to 200 characters and pagination uses a fixed page
size of ten. Booking response fields are read-only to clients.

Validation errors use the API's standard error envelope, for example:

```json
{
  "success": false,
  "status_code": 400,
  "message": "Validation failed.",
  "errors": {"email": ["Enter a valid email address."]}
}
```

Rate-limit responses use HTTP 429 and the same envelope with
`"status_code": 429`. Do not log passwords, tokens, Razorpay secrets,
signatures, or complete webhook bodies.

For production set `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, and
`SECRET_KEY` through the environment. HTTPS redirect, secure session/CSRF
cookies, and HSTS are enabled by default when debug is disabled; tune them
with the `DJANGO_SECURE_*` variables for the deployment. Set
`DJANGO_CSRF_TRUSTED_ORIGINS` for trusted admin/browser origins and enable
`DJANGO_TRUST_X_FORWARDED_PROTO` only behind a trusted proxy. This API uses
bearer JWTs rather than cookie authentication; use a same-origin frontend
proxy or configure an exact CORS allowlist at the deployment gateway instead
of allowing every origin.

Refresh tokens rotate and previous refresh tokens are blacklisted. Apply
Django migrations when deploying this setting because SimpleJWT's token
blacklist app stores outstanding and revoked refresh tokens.

Run the security-focused tests with:

```bash
pytest accounts/test_security.py bookings/tests/test_api_security.py
```

---

##  Results & Metrics



| Test | Result |
|---|---|
| Concurrency test | 500 requests for 50 seats → 50 bookings, 0 double-bookings |
| Idempotency test | 20 retries → 1 charge, 1 booking |
| Webhook test | 100 duplicate events → no duplicate payments |
| Hold expiry | Seats released within ~N seconds |
| Throughput (load test) | Requests/sec and p95 latency (actual measured values) |
| Query optimization | `EXPLAIN ANALYZE` before/after indexes (e.g. 120 ms → 8 ms) |
| Test coverage | Number of tests and coverage % |
| Deployment | Live API URL and working demo |

---

##  Concepts Covered

- Django & DRF (models, serializers, viewsets)
- PostgreSQL design & indexing
- Transactions and row locking
- Concurrency and race conditions
- Razorpay payments and webhooks
- Celery and background processing
- Redis caching and rate limiting
- JWT authentication
- Testing with pytest
- Docker and deployment
- API documentation (OpenAPI)
- Performance testing and optimization

---

## Final Outcome

- Fully functional Django ticket booking backend
- Handles concurrent bookings correctly
- Integrated with Razorpay (test mode)
- Background jobs with Celery
- Redis caching and rate limiting
- Tested, dockerized and deployed
- Well-documented with real results

---

##  License

MIT (or your preferred license)
