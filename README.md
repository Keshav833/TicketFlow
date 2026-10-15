
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

### Running tests

```bash
docker compose exec web pytest
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
