import os
from datetime import date, datetime, timedelta, timezone
from fastapi import status
from app.config import settings


def test_create_booking_success(client):
    """Customer can successfully book an open slot."""
    target_dt = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    payload = {
        "customer_name": "Jane Doe",
        "customer_email": "jane@example.com",
        "customer_phone": "+1-555-0199",
        "stylist_id": 1,
        "service_id": 1,  # 30-minute haircut
        "start_time": target_dt.isoformat(),
    }
    res = client.post("/api/v1/bookings", json=payload)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["id"] > 0
    assert data["customer_name"] == "Jane Doe"
    assert data["status"] == "CONFIRMED"
    assert data["service_price_cents"] == 3500
    assert data["cancellation_fee_cents"] == 0
    assert data["end_time"].endswith("11:30:00")


def test_create_booking_blank_name_returns_422(client):
    """Whitespace or empty customer name fails validation."""
    target_dt = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    payload = {
        "customer_name": "   ",
        "customer_email": "jane@example.com",
        "customer_phone": "+1-555-0199",
        "stylist_id": 1,
        "service_id": 1,
        "start_time": target_dt.isoformat(),
    }
    res = client.post("/api/v1/bookings", json=payload)
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_booking_invalid_email_returns_422(client):
    """Invalid email format fails validation."""
    target_dt = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    payload = {
        "customer_name": "Jane Doe",
        "customer_email": "not-an-email",
        "customer_phone": "+1-555-0199",
        "stylist_id": 1,
        "service_id": 1,
        "start_time": target_dt.isoformat(),
    }
    res = client.post("/api/v1/bookings", json=payload)
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_booking_nonexistent_stylist_returns_404(client):
    target_dt = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    payload = {
        "customer_name": "Jane Doe",
        "customer_email": "jane@example.com",
        "customer_phone": "+1-555-0199",
        "stylist_id": 9999,
        "service_id": 1,
        "start_time": target_dt.isoformat(),
    }
    res = client.post("/api/v1/bookings", json=payload)
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_create_booking_nonexistent_service_returns_404(client):
    target_dt = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    payload = {
        "customer_name": "Jane Doe",
        "customer_email": "jane@example.com",
        "customer_phone": "+1-555-0199",
        "stylist_id": 1,
        "service_id": 9999,
        "start_time": target_dt.isoformat(),
    }
    res = client.post("/api/v1/bookings", json=payload)
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_create_booking_inactive_stylist_returns_400(client):
    target_dt = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    payload = {
        "customer_name": "Jane Doe",
        "customer_email": "jane@example.com",
        "customer_phone": "+1-555-0199",
        "stylist_id": 3,  # Inactive stylist
        "service_id": 1,
        "start_time": target_dt.isoformat(),
    }
    res = client.post("/api/v1/bookings", json=payload)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "inactive" in res.json()["detail"].lower()


def test_create_booking_outside_working_hours_returns_400(client):
    early_dt = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=7, minute=0, second=0, microsecond=0
    )
    res_early = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Early Bird",
            "customer_email": "early@example.com",
            "customer_phone": "+1-555-0199",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": early_dt.isoformat(),
        },
    )
    assert res_early.status_code == status.HTTP_400_BAD_REQUEST

    late_dt = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=16, minute=45, second=0, microsecond=0
    )
    res_late = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Late Owl",
            "customer_email": "late@example.com",
            "customer_phone": "+1-555-0199",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": late_dt.isoformat(),
        },
    )
    assert res_late.status_code == status.HTTP_400_BAD_REQUEST


def test_create_booking_in_the_past_returns_400(client):
    past_dt = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    res = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Time Traveler",
            "customer_email": "past@example.com",
            "customer_phone": "+1-555-0199",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": past_dt.isoformat(),
        },
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "past" in res.json()["detail"].lower()


def test_create_booking_overlapping_middle_returns_409(client):
    """Booking that overlaps the middle of an existing booking must be rejected with 409 Conflict."""
    target_dt = (datetime.now(timezone.utc) + timedelta(days=4)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    # Existing booking: 14:00 - 14:30
    res1 = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "First Customer",
            "customer_email": "first@example.com",
            "customer_phone": "+1-555-0199",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": target_dt.isoformat(),
        },
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # Conflicting booking: 14:15 - 14:45
    conflict_dt = target_dt + timedelta(minutes=15)
    res2 = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Second Customer",
            "customer_email": "second@example.com",
            "customer_phone": "+1-555-0299",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": conflict_dt.isoformat(),
        },
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already booked" in res2.json()["detail"].lower()


def test_cancel_booking_success_and_frees_up_slot(client):
    """Cancelling a booking marks it CANCELLED and frees up the slot for other customers."""
    target_dt = (datetime.now(timezone.utc) + timedelta(days=4)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    res_book = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Alice Cooper",
            "customer_email": "alice@example.com",
            "customer_phone": "+1-555-0199",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": target_dt.isoformat(),
        },
    )
    assert res_book.status_code == status.HTTP_201_CREATED
    booking_id = res_book.json()["id"]

    # Cancel booking
    res_cancel = client.post(f"/api/v1/bookings/{booking_id}/cancel")
    assert res_cancel.status_code == status.HTTP_200_OK
    cancel_data = res_cancel.json()
    assert cancel_data["booking"]["status"] == "CANCELLED"
    assert cancel_data["cancellation_fee_cents"] == 0

    # Repeating cancel on already cancelled booking must return 400
    res_repeat = client.post(f"/api/v1/bookings/{booking_id}/cancel")
    assert res_repeat.status_code == status.HTTP_400_BAD_REQUEST

    # Another customer can now book that exact same slot
    res_rebook = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Bob Dylan",
            "customer_email": "bob@example.com",
            "customer_phone": "+1-555-9999",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": target_dt.isoformat(),
        },
    )
    assert res_rebook.status_code == status.HTTP_201_CREATED
    assert res_rebook.json()["status"] == "CONFIRMED"


def test_cancel_nonexistent_booking_returns_404(client):
    res = client.post("/api/v1/bookings/99999/cancel")
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_staff_bookings_requires_auth(client, staff_headers):
    """Staff booking list must reject requests without valid staff key."""
    # 1. No key -> 401
    res_no_key = client.get("/api/v1/staff/bookings")
    assert res_no_key.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Invalid key -> 401
    auth_header_key = "X-API-Key"
    unauthorized_key = f"{settings.STAFF_API_KEY}-unauthorized-attempt"
    res_bad_key = client.get("/api/v1/staff/bookings", headers={auth_header_key: unauthorized_key})
    assert res_bad_key.status_code == status.HTTP_401_UNAUTHORIZED

    # 3. Valid key -> 200
    res_auth = client.get("/api/v1/staff/bookings", headers=staff_headers)
    assert res_auth.status_code == status.HTTP_200_OK
    assert isinstance(res_auth.json(), list)
