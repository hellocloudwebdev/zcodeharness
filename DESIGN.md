# Salon Booking Backend Architecture & Technical Design

## 1. System Overview & Goals
The salon booking backend enables customers to browse services and stylist availability, schedule appointments without double-booking, cancel, and reschedule. Staff can inspect schedules and manage holidays via an authenticated API.

### Core Constraints & Invariants
- **Stack**: Python 3.13, FastAPI, SQLite (via SQLAlchemy 2.0 and Pydantic v2).
- **Concurrency & Invariant**: A stylist must never be double-booked across overlapping time windows for active bookings.
- **Service Durations**: Flexible durations (e.g., Haircut = 30 min, Coloring = 120 min).
- **Working Hours**: Staff work defined hours (e.g., 09:00 - 17:00). Bookings cannot start before or end after working hours.
- **Holidays**: The salon can declare calendar holidays where bookings are blocked.
- **Cancellation Policy**: Free if cancelled > 24 hours prior to appointment; 50% service fee if cancelled within 24 hours.

---

## 2. Folder Structure
```text
D:\SCAN\Tasks/
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app, lifespan event, CORS, exception handlers
│   ├── config.py                 # Environment settings (API keys, DB URL, Salon defaults)
│   ├── database.py               # SQLAlchemy engine, sessionmaker, SQLite WAL & locking setup
│   ├── models.py                 # Database models (Stylist, Service, Booking, Holiday)
│   ├── schemas.py                # Pydantic v2 request/response schemas
│   ├── auth.py                   # Staff API Key authentication dependency
│   ├── services/
│   │   ├── __init__.py
│   │   ├── availability_service.py # Slot calculation, working hours, holiday exclusions
│   │   └── booking_service.py      # Transactional booking creation, cancellation, reschedule
│   └── routers/
│       ├── __init__.py
│       ├── availability.py       # Public slot query endpoint
│       ├── bookings.py           # Customer booking, cancellation, rescheduling endpoints
│       ├── catalog.py            # Public service & stylist listing
│       └── staff.py              # Protected staff management & holiday endpoints
├── tests/
│   ├── __init__.py
│   ├── conftest.py               # Pytest fixtures, test DB, test client
│   ├── test_availability.py      # Slot computation and working hours validation
│   ├── test_bookings.py          # Creation, listing, cancellation, validation (400/404/409)
│   ├── test_concurrency_bugs.py  # Phase 3 race condition & adjacent interval boundary tests
│   └── test_change_requests.py   # Phase 4 rescheduling, cancellation fees, holidays
├── DESIGN.md                     # Architectural specification (this document)
├── README.md                     # Deployment and developer manual
├── REVIEW.md                     # Code audit, weaknesses, fixes, confidence assessment
├── Dockerfile                    # Container definition
├── requirements.txt              # Pinned Python dependencies
└── pytest.ini                    # Test runner configuration
```

---

## 3. Data Model

### Relational Schema (SQLite)

```sql
CREATE TABLE stylists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    work_start_time TEXT NOT NULL DEFAULT '09:00:00', -- Stored as HH:MM:SS
    work_end_time TEXT NOT NULL DEFAULT '17:00:00',
    is_active BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    price_cents INTEGER NOT NULL -- Stored as integer cents ($30.00 = 3000)
);

CREATE TABLE bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    customer_phone TEXT NOT NULL,
    stylist_id INTEGER NOT NULL REFERENCES stylists(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    start_time TEXT NOT NULL, -- ISO-8601 UTC timestamp: YYYY-MM-DDTHH:MM:SS
    end_time TEXT NOT NULL,   -- start_time + duration_minutes
    status TEXT NOT NULL DEFAULT 'CONFIRMED', -- 'CONFIRMED', 'CANCELLED', 'RESCHEDULED'
    service_price_cents INTEGER NOT NULL,    -- Snapshot of service price at booking
    cancellation_fee_cents INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_bookings_stylist_time 
    ON bookings (stylist_id, start_time, end_time) 
    WHERE status != 'CANCELLED';

CREATE TABLE holidays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE, -- Stored as YYYY-MM-DD
    description TEXT NOT NULL
);
```

---

## 4. Main API Endpoints

### Public Endpoints (Customers)
| Method | Endpoint | Description | Status Codes |
|---|---|---|---|
| `GET` | `/api/v1/catalog/services` | List all available salon services | 200 |
| `GET` | `/api/v1/catalog/stylists` | List active stylists | 200 |
| `GET` | `/api/v1/availability` | List open slots for `stylist_id`, `service_id`, and `date` | 200, 400, 404 |
| `POST` | `/api/v1/bookings` | Book an appointment | 201, 400, 404, 409 |
| `GET` | `/api/v1/bookings/{id}` | Retrieve booking details | 200, 404 |
| `POST` | `/api/v1/bookings/{id}/cancel` | Cancel booking (calculates fee based on 24h rule) | 200, 400, 404 |
| `POST` | `/api/v1/bookings/{id}/reschedule` | Reschedule booking to new start time | 200, 400, 404, 409 |

### Staff Endpoints (Protected by Header `X-API-Key`)
| Method | Endpoint | Description | Status Codes |
|---|---|---|---|
| `GET` | `/api/v1/staff/bookings` | List all bookings (filters: date, stylist_id, status) | 200, 401 |
| `POST` | `/api/v1/staff/holidays` | Declare a salon holiday | 201, 400, 401, 409 |
| `GET` | `/api/v1/staff/holidays` | List registered holidays | 200, 401 |
| `DELETE` | `/api/v1/staff/holidays/{id}` | Delete a holiday | 204, 401, 404 |

---

## 5. Preventing Double-Booking: Decision & Comparison

### Comparison of Options

#### Option A: Application Check Only
- **Mechanism**: The backend runs `SELECT 1 FROM bookings WHERE stylist_id = :id AND status != 'CANCELLED' AND start_time < :new_end AND end_time > :new_start`. If a record exists, return HTTP 409 Conflict; otherwise `INSERT`.
- **Pros**: Easy to write; clear error messages; works across any database engine.
- **Cons**: Vulnerable to race conditions (Time-of-Check to Time-of-Use / TOCTOU). Two concurrent requests hitting the server simultaneously both see zero conflicts in their read phase and both execute `INSERT`, resulting in double-booking.

#### Option B: Database Constraint Only
- **Mechanism**: Use database native exclusion constraints. For PostgreSQL, `EXCLUDE USING gist (stylist_id WITH =, tsrange(start_time, end_time) WITH &&)`.
- **Pros**: 100% atomic at storage layer; impossible for application-level concurrency bugs to bypass.
- **Cons**: **SQLite does not support GiST exclusion constraints or tsrange types.** A simple `UNIQUE(stylist_id, start_time)` is inadequate because services have varying durations (e.g., a 120-minute coloring starting at 10:00 will not trigger a unique constraint violation when a 30-minute haircut is inserted at 10:30, yet they overlap). Emulating exclusion constraints in SQLite requires either discrete time-slice rows (e.g. 15-minute slot tables) or custom triggers.

#### Option C: Committed Architecture — Strict Transactional Locking (`BEGIN IMMEDIATE`) + Half-Open Interval Application Check
- **Commitment**: **Option C (Application check within an immediate write-locked transaction).**
- **Justification**:
  1. In SQLite, transactions default to `DEFERRED`, meaning locks are not acquired until a write statement is executed. This creates a concurrency window between `SELECT` and `INSERT`.
  2. By initiating booking transactions with `BEGIN IMMEDIATE` (configured at connection/session level via SQLAlchemy event listeners or explicit execution), SQLite acquires a RESERVED lock immediately before the conflict `SELECT` runs.
  3. No other writer can enter `BEGIN IMMEDIATE` or acquire a write lock until the transaction finishes.
  4. The conflict query uses mathematically sound **half-open intervals** `[start, end)`:
     $$	ext{Overlap} \iff (	ext{new\_start} < 	ext{existing\_end}) \land (	ext{new\_end} > 	ext{existing\_start})$$
     This guarantees that adjacent bookings (e.g. 09:00–09:30 and 09:30–10:00) are accepted, while any true intersection is blocked.
  5. Cancelled bookings (`status = 'CANCELLED'`) are explicitly excluded from the conflict filter.

---

## 6. Three Production Risks and Mitigations

### Risk 1: SQLite Lock Contention (`OperationalError: database is locked`)
- **Risk**: SQLite allows only one active writer at any time. When multiple customers attempt to book or cancel simultaneously, slow queries or long transactions can hold the write lock, causing concurrent requests to time out with `database is locked`.
- **Mitigation**:
  - Enable Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) and `PRAGMA synchronous = NORMAL;` on connection setup. WAL allows concurrent readers while a writer is active.
  - Set SQLite busy timeout to 30 seconds (`PRAGMA busy_timeout = 30000;`) so brief write contention queues rather than instantly failing.
  - Keep write transactions extremely short: compute validation outside the transaction, lock immediately with `BEGIN IMMEDIATE`, run the fast index-backed overlap query, insert, and commit immediately.
  - Establish a clean migration path to PostgreSQL with GiST exclusion constraints when scaling beyond single-node SQLite.

### Risk 2: Timezone Ambiguity and Daylight Saving Time (DST) Transitions
- **Risk**: If clients send local timestamps or if the server interprets datetime strings under shifting local rules, bookings can shift by 1 hour during DST changes. This leads to false overlaps, missed appointments, or staff working outside their real business hours.
- **Mitigation**:
  - Salon hours and holiday dates are anchored to the Salon's physical timezone (`America/New_York` or configured standard local zone).
  - All API booking timestamps must be ISO-8601 strings, parsed and converted to timezone-aware UTC datetime objects before database storage.
  - Working hours (09:00–17:00) are evaluated against the salon's local wall-clock time for the requested appointment date.

### Risk 3: Service Catalog and Pricing Drift Over Time
- **Risk**: If salon management changes the duration or price of a service (e.g., haircut increases from $30 to $40 or 30 min to 45 min), existing scheduled bookings or historical financial reports could be corrupted if durations and prices are dynamically joined from the `services` table.
- **Mitigation**:
  - **Snapshotting**: When a booking is created, both `end_time` (precalculated from current duration) and `service_price_cents` are stored directly on the `bookings` row.
  - Modifications to the service catalog only affect future bookings; historical and already-scheduled appointments preserve their contracted duration and price snapshot.

---

## 7. Change Request Architectural Decisions (Phase 4)

### 7.1 Modeling Cancellation Fees
- **Committed Model**:
  - Stored `cancellation_fee_cents INTEGER` on the `bookings` table, alongside snapshotted `service_price_cents INTEGER`.
  - When a booking is cancelled via `POST /api/v1/bookings/{id}/cancel`:
    $$	ext{fee} = \begin{cases} 0 & 	ext{if } (	ext{start\_time} - 	ext{now}) > 24 	ext{ hours} \\ \lfloor 	ext{service\_price\_cents} / 2 \rfloor & 	ext{if } (	ext{start\_time} - 	ext{now}) \le 24 	ext{ hours} \end{cases}$$
  - The fee is permanently recorded onto the booking row at the moment of cancellation.
- **What Was Rejected**:
  1. *Dynamic on-the-fly calculation at query time*: Calculating the fee whenever a booking is viewed was rejected because if the service price later changes or if time passes after cancellation, the fee would retroactively shift. Persisting `cancellation_fee_cents` creates an immutable audit trail.
  2. *Floating-point representation (e.g. $17.50)*: Using floating-point values was rejected due to IEEE-754 precision rounding issues. Integer cents guarantee exact financial balance reconciliation.

### 7.2 Modeling Salon Holidays
- **Committed Model**:
  - Dedicated `holidays` table with `date DATE UNIQUE NOT NULL` and `description TEXT NOT NULL`.
  - Filtered at the top of slot availability generation (`get_stylist_availability` returns 0 slots on holidays).
  - Validated during booking creation and rescheduling (`POST /bookings` and `POST /bookings/{id}/reschedule` return `409 Conflict` if the requested date is a holiday).
  - Managed by salon staff via authenticated CRUD endpoints (`/api/v1/staff/holidays`).
- **What Was Rejected**:
  1. *Hardcoded calendar configurations in code or YAML*: Rejected because holidays change dynamically (emergency closures, weather days, staff retreats) and salon operators need to add/remove holidays without code deployments or server restarts.
  2. *Generating dummy "blocker bookings" across all stylists*: Rejected because creating synthetic bookings for every stylist on every holiday creates $O(	ext{stylists} 	imes 	ext{slots})$ database clutter, skews analytics, and fails when new stylists are added after the blocker bookings were seeded. A clean relational `holidays` table provides $O(1)$ indexed lookup.

### 7.3 Modeling Rescheduling
- **Committed Model**:
  - `POST /api/v1/bookings/{id}/reschedule` accepts a new start time.
  - Checks: ensures booking is active, new time is in the future, date is not a holiday, within working hours, and does not conflict with any *other* booking (`Booking.id != booking_id`).
  - Executes inside the immediate write-lock transaction to prevent race conditions.
- **What Was Rejected**:
  1. *Cancel-and-Recreate workflow*: Forcing the client to cancel the old booking and create a new one was rejected because it would incorrectly trigger the cancellation fee rule if rescheduled within 24 hours. Rescheduling preserves the booking identity and customer information while updating the slot atomically.

