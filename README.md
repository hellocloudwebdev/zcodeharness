# 💇‍♀️ Salon Appointment Booking Backend API

A high-reliability backend API built with **Python**, **FastAPI**, and **SQLite** (via SQLAlchemy 2.0 & Pydantic v2) for small to mid-sized salons.

---

## 🌟 Key Features
- **Online Customer Booking**: Customers can browse stylists and services, query real-time available time slots, book appointments, cancel, and reschedule.
- **Strict Double-Booking Prevention**: Mathematical half-open interval overlap detection ($S_1 < E_2 \land E_1 > S_2$) paired with SQLite `BEGIN IMMEDIATE` transaction locking to eliminate concurrency race conditions.
- **Flexible Service Durations**: Automatically accounts for different appointment lengths (e.g., 30-minute haircut vs. 120-minute hair coloring).
- **Stylist Working Hours**: Enforces start and end times (default 09:00 - 17:00) converted to the salon's physical wall-clock timezone.
- **Cancellation Fee Rules**: Free cancellation if cancelled $> 24	ext{h}$ in advance; automatic 50% service fee recorded if cancelled $\le 24	ext{h}$ prior.
- **Salon Holidays**: Staff can declare holidays where all bookings and available slots are automatically blocked.
- **Cryptographic IDOR Protection**: Each booking issues a secure random management token (`manage_token`) so only the customer who booked can cancel or reschedule.
- **Role-Based Security**: Public customer endpoints for seamless booking; staff endpoints protected by an `X-API-Key` header.

---

## 📂 Project Structure
```text
.
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI application factory, lifespan, CORS, seed logic
│   ├── config.py                 # Configuration settings (environment variables, defaults)
│   ├── database.py               # SQLAlchemy engine, sessionmaker, SQLite WAL/timeout pragmas
│   ├── models.py                 # Database models (Stylist, Service, Booking, Holiday)
│   ├── schemas.py                # Pydantic v2 schemas and validation logic
│   ├── auth.py                   # Staff API Key authentication dependency
│   ├── services/
│   │   ├── __init__.py
│   │   ├── availability_service.py # Slot generation, working hours & holiday filters
│   │   └── booking_service.py      # Concurrency-safe booking, rescheduling & fee logic
│   └── routers/
│       ├── __init__.py
│       ├── catalog.py            # Public service & stylist listing
│       ├── availability.py       # Public slot availability endpoint
│       ├── bookings.py           # Customer booking, cancel, reschedule endpoints
│       └── staff.py              # Protected staff management & holiday administration
├── tests/
│   ├── __init__.py
│   ├── conftest.py               # Isolated test database fixtures & TestClient
│   ├── test_availability.py      # Slot computation and working hours validation
│   ├── test_bookings.py          # Booking creation, input validation, cancellation, staff auth
│   ├── test_concurrency_bugs.py  # Concurrency race reproduction and adjacent boundary tests
│   └── test_change_requests.py   # Rescheduling, 24h fee rules, holidays, and IDOR token tests
├── DESIGN.md                     # Technical architecture, concurrency choices, production risks
├── REVIEW.md                     # Technical audit, 5 real weaknesses, fixes, confidence assessment
├── Dockerfile                    # Production containerization
├── requirements.txt              # Pinned Python dependencies
└── pytest.ini                    # Pytest configuration
```

---

## 🚀 Quickstart for Junior Developers

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.13)
- `pip` and `virtualenv`

### 2. Local Setup
Clone or navigate to the project directory:
```bash
# 1. Create a virtual environment
python -m venv venv

# 2. Activate virtual environment
# On Linux / macOS:
source venv/bin/activate
# On Windows (Git Bash):
source venv/Scripts/activate
# On Windows (cmd):
venv\Scripts\activate.bat

# 3. Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables (Optional)
The application works out of the box with sensible defaults. To customize, create a `.env` file:
```env
DATABASE_URL=sqlite:///./salon.db
STAFF_API_KEY=your-secure-staff-secret-key
SALON_TIMEZONE=UTC
SALON_OPEN_TIME=09:00:00
SALON_CLOSE_TIME=17:00:00
```

### 4. Running the Development Server
```bash
uvicorn app.main:app --reload --port 8000
```
The server will automatically:
1. Initialize the SQLite database schema (`salon.db`).
2. Configure SQLite Write-Ahead Logging (`WAL` mode) and a 30-second busy timeout.
3. Seed default stylists (*Alice Smith*, *Bob Jones*) and services (*Haircut*, *Coloring*, *Beard Trim*).

Open interactive Swagger documentation in your browser:
👉 [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🧪 Running Automated Tests
Run the entire test suite using `pytest`:
```bash
pytest
```
To run with detailed test execution:
```bash
pytest -v
```
All 26 tests run in an isolated temporary SQLite database and take ~1 second to finish.

---

## 🐳 Docker Deployment

### 1. Build the Docker Image
```bash
docker build -t salon-booking-api:latest .
```

### 2. Run the Container
```bash
docker run -d \
  --name salon-api \
  -p 8000:8000 \
  -e STAFF_API_KEY="production-secret-key" \
  -e SALON_TIMEZONE="America/New_York" \
  -v $(pwd)/data:/app/data \
  salon-booking-api:latest
```

The container runs as a non-root user `salon` and includes a built-in Docker `HEALTHCHECK`.

---

## 📖 API Documentation & Endpoints

### Public Endpoints (Customers)

#### 1. List Services
- **Method**: `GET /api/v1/catalog/services`
- **Response**: List of services with duration in minutes and price in cents.
```bash
curl -X GET http://localhost:8000/api/v1/catalog/services
```

#### 2. List Stylists
- **Method**: `GET /api/v1/catalog/stylists`
```bash
curl -X GET http://localhost:8000/api/v1/catalog/stylists
```

#### 3. Check Slot Availability
- **Method**: `GET /api/v1/availability?stylist_id=1&service_id=1&date=2026-10-30`
```bash
curl -X GET "http://localhost:8000/api/v1/availability?stylist_id=1&service_id=1&date=2026-10-30"
```

#### 4. Book an Appointment
- **Method**: `POST /api/v1/bookings`
- **Request Body**:
```json
{
  "customer_name": "Sarah Connor",
  "customer_email": "sarah@example.com",
  "customer_phone": "+1-555-0199",
  "stylist_id": 1,
  "service_id": 1,
  "start_time": "2026-10-30T10:00:00"
}
```
- **Response**: Returns 201 Created with booking details and the `manage_token`.

#### 5. Cancel an Appointment
- **Method**: `POST /api/v1/bookings/{id}/cancel?token={manage_token}`
- **Response**: 200 OK with `cancellation_fee_cents` (0 if $>24	ext{h}$, 50% if $\le 24	ext{h}$).

#### 6. Reschedule an Appointment
- **Method**: `POST /api/v1/bookings/{id}/reschedule`
- **Request Body**:
```json
{
  "new_start_time": "2026-10-30T14:00:00",
  "manage_token": "your-manage-token"
}
```

---

### Staff Endpoints (Protected by `X-API-Key`)

#### 1. List All Bookings
- **Method**: `GET /api/v1/staff/bookings`
- **Headers**: `X-API-Key: salon-staff-secret-key-2026`
- **Query Params**: `stylist_id`, `booking_date`, `status`
```bash
curl -X GET http://localhost:8000/api/v1/staff/bookings \
  -H "X-API-Key: dev-staff-key-change-in-production"
```

#### 2. Declare a Holiday
- **Method**: `POST /api/v1/staff/holidays`
- **Headers**: `X-API-Key: salon-staff-secret-key-2026`
- **Request Body**:
```json
{
  "date": "2026-12-25",
  "description": "Christmas Day - Salon Closed"
}
```

#### 3. Remove a Holiday
- **Method**: `DELETE /api/v1/staff/holidays/{id}`
- **Headers**: `X-API-Key: salon-staff-secret-key-2026`
