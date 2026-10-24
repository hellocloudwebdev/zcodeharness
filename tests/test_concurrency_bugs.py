from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from fastapi import status
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.models import Booking


def test_reproduce_adjacent_booking_boundary_rejected(client):
    """
    BUG 1 VERIFICATION:
    'Bookings that end exactly when another starts are wrongly rejected.'
    Booking A: 09:00 - 09:30
    Booking B: 09:30 - 10:00 (ends exactly when A starts or starts exactly when A ends)
    With half-open interval checks (start_time < end_time and end_time > start_time),
    Booking B must succeed with 201 Created.
    """
    target_dt = (datetime.now(timezone.utc) + timedelta(days=10)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    # Booking A: 09:00 - 09:30
    res_a = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Customer A",
            "customer_email": "customer.a@example.com",
            "customer_phone": "555-0001",
            "stylist_id": 1,
            "service_id": 1,  # 30 min haircut
            "start_time": target_dt.isoformat(),
        },
    )
    assert res_a.status_code == status.HTTP_201_CREATED

    # Booking B: 09:30 - 10:00 (adjacent back-to-back slot)
    adjacent_dt = target_dt + timedelta(minutes=30)
    res_b = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Customer B",
            "customer_email": "customer.b@example.com",
            "customer_phone": "555-0002",
            "stylist_id": 1,
            "service_id": 1,  # 30 min haircut
            "start_time": adjacent_dt.isoformat(),
        },
    )
    assert res_b.status_code == status.HTTP_201_CREATED
    assert res_b.json()["start_time"].endswith("09:30:00")
    assert res_b.json()["end_time"].endswith("10:00:00")


def test_reproduce_concurrent_double_booking(test_db):
    """
    BUG 2 VERIFICATION:
    'Two customers sometimes get the same slot.'
    When two requests attempt to book the identical slot concurrently,
    atomic serialization ensures exactly one succeeds (201) and the other is rejected (409).
    """
    session_factory = test_db["session_factory"]

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    target_dt = (datetime.now(timezone.utc) + timedelta(days=11)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )

    def attempt_booking(customer_num: int):
        with TestClient(app) as local_client:
            payload = {
                "customer_name": f"Customer Race {customer_num}",
                "customer_email": f"race{customer_num}@example.com",
                "customer_phone": f"555-999{customer_num}",
                "stylist_id": 2,
                "service_id": 1,  # 30 min haircut
                "start_time": target_dt.isoformat(),
            }
            res = local_client.post("/api/v1/bookings", json=payload)
            return res.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_booking, 1)
        f2 = executor.submit(attempt_booking, 2)
        status_codes = [f1.result(), f2.result()]

    app.dependency_overrides.clear()

    # Exactly one request gets 201 Created and the other gets 409 Conflict
    assert status.HTTP_201_CREATED in status_codes, f"Expected a successful booking, got {status_codes}"
    assert status.HTTP_409_CONFLICT in status_codes, f"Expected a 409 Conflict, got {status_codes}"
    assert status_codes.count(status.HTTP_201_CREATED) == 1
    assert status_codes.count(status.HTTP_409_CONFLICT) == 1

    # Verify database state has exactly 1 active booking
    db = session_factory()
    active_bookings = (
        db.query(Booking)
        .filter(Booking.stylist_id == 2, Booking.status == "CONFIRMED")
        .all()
    )
    db.close()
    assert len(active_bookings) == 1
