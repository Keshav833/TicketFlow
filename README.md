
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
├── tickets/
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── services.py
│   ├── tasks.py
│   └── tests/
├── users/
├── payments/
├── core/
├── config/
├── docker/
├── tests/
├── README.md
├── docker-compose.yml
└── requirements.txt
```

---

##  Getting Started

```bash
# 1. Clone
git clone https://github.com/<your-username>/ticketflow.git
cd ticketflow

# 2. Environment variables
cp .env.example .env     # add DB, Redis, Razorpay test keys, JWT secret

# 3. Run the full stack (Django, Postgres, Redis, Celery)
docker compose up --build

# 4. Migrations & admin user
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

- API docs (Swagger): `http://localhost:8000/api/docs/`
- Admin: `http://localhost:8000/admin/`

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
