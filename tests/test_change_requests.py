from datetime import date, datetime, timedelta, timezone
from fastapi import status


def test_cancellation_fee_tiering(client):
    """
    Test cancellation fee policy:
    - Free if cancelled > 24 hours prior
    - 50% of service price if cancelled <= 24 hours prior
    """
    now_utc = datetime.now(timezone.utc)

    # 1. Booking far in advance (>24h): 3 days ahead
    future_dt = (now_utc + timedelta(days=3)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    res_far = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Early Bird",
            "customer_email": "early@example.com",
            "customer_phone": "555-0101",
            "stylist_id": 1,
            "service_id": 1,  # $35.00 = 3500 cents
            "start_time": future_dt.isoformat(),
        },
    )
    assert res_far.status_code == status.HTTP_201_CREATED
    far_id = res_far.json()["id"]

    cancel_far = client.post(f"/api/v1/bookings/{far_id}/cancel")
    assert cancel_far.status_code == status.HTTP_200_OK
    assert cancel_far.json()["cancellation_fee_cents"] == 0

    # 2. Booking within 24 hours: the next upcoming 10:00 AM is always within 24 hours
    next_10am = now_utc.replace(hour=10, minute=0, second=0, microsecond=0)
    if next_10am <= now_utc:
        next_10am += timedelta(days=1)

    time_diff = next_10am - now_utc
    assert timedelta(0) < time_diff <= timedelta(hours=24)

    res_near = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Last Minute",
            "customer_email": "late@example.com",
            "customer_phone": "555-0102",
            "stylist_id": 1,
            "service_id": 2,  # Coloring: $120.00 = 12000 cents
            "start_time": next_10am.isoformat(),
        },
    )
    assert res_near.status_code == status.HTTP_201_CREATED
    near_id = res_near.json()["id"]

    cancel_near = client.post(f"/api/v1/bookings/{near_id}/cancel")
    assert cancel_near.status_code == status.HTTP_200_OK
    # 50% of 12000 cents = 6000 cents ($60.00)
    assert cancel_near.json()["cancellation_fee_cents"] == 6000
    assert cancel_near.json()["booking"]["cancellation_fee_cents"] == 6000


def test_reschedule_booking_success(client):
    """Customer can reschedule a confirmed booking to an open future slot."""
    original_dt = (datetime.now(timezone.utc) + timedelta(days=5)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    res_orig = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Mona Lisa",
            "customer_email": "mona@example.com",
            "customer_phone": "555-0103",
            "stylist_id": 1,
            "service_id": 1,  # 30 min
            "start_time": original_dt.isoformat(),
        },
    )
    assert res_orig.status_code == status.HTTP_201_CREATED
    booking_id = res_orig.json()["id"]

    # Reschedule to 14:00 on the same day
    new_dt = original_dt.replace(hour=14, minute=0)
    res_resched = client.post(
        f"/api/v1/bookings/{booking_id}/reschedule",
        json={"new_start_time": new_dt.isoformat()},
    )
    assert res_resched.status_code == status.HTTP_200_OK
    data = res_resched.json()
    assert data["start_time"].endswith("14:00:00")
    assert data["end_time"].endswith("14:30:00")
    assert data["status"] == "CONFIRMED"

    # Verify original slot 10:00 is now free again!
    res_rebook_old_slot = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "New Person",
            "customer_email": "new@example.com",
            "customer_phone": "555-0104",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": original_dt.isoformat(),
        },
    )
    assert res_rebook_old_slot.status_code == status.HTTP_201_CREATED


def test_reschedule_to_conflicting_slot_rejected(client):
    """Rescheduling to a slot occupied by another customer must return 409 Conflict."""
    day = (datetime.now(timezone.utc) + timedelta(days=6)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    # Booking 1: 10:00 - 10:30
    b1 = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "User One",
            "customer_email": "u1@example.com",
            "customer_phone": "555-0105",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": day.isoformat(),
        },
    ).json()

    # Booking 2: 11:00 - 11:30
    b2_time = day.replace(hour=11)
    b2 = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "User Two",
            "customer_email": "u2@example.com",
            "customer_phone": "555-0106",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": b2_time.isoformat(),
        },
    ).json()

    # User 2 attempts to reschedule to 10:00 (already booked by User 1)
    res_conflict = client.post(
        f"/api/v1/bookings/{b2['id']}/reschedule",
        json={"new_start_time": day.isoformat()},
    )
    assert res_conflict.status_code == status.HTTP_409_CONFLICT
    assert "already booked" in res_conflict.json()["detail"].lower()


def test_reschedule_cancelled_booking_fails(client):
    day = (datetime.now(timezone.utc) + timedelta(days=7)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    b = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "User Three",
            "customer_email": "u3@example.com",
            "customer_phone": "555-0107",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": day.isoformat(),
        },
    ).json()

    # Cancel it
    client.post(f"/api/v1/bookings/{b['id']}/cancel")

    # Try rescheduling cancelled booking
    new_time = day.replace(hour=14)
    res = client.post(
        f"/api/v1/bookings/{b['id']}/reschedule",
        json={"new_start_time": new_time.isoformat()},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "cancelled" in res.json()["detail"].lower()


def test_holiday_management_and_booking_block(client, staff_headers):
    """
    Test Salon Holidays:
    - Staff registers a holiday
    - Public availability returns 0 slots
    - Attempting to book or reschedule on holiday returns 409 Conflict
    - Deleting the holiday reopens the date
    """
    holiday_date = (date.today() + timedelta(days=12)).isoformat()

    # 1. Register holiday via staff endpoint
    res_holiday = client.post(
        "/api/v1/staff/holidays",
        headers=staff_headers,
        json={"date": holiday_date, "description": "Salon Annual Staff Retreat"},
    )
    assert res_holiday.status_code == status.HTTP_201_CREATED
    holiday_id = res_holiday.json()["id"]

    # Duplicate holiday should be rejected
    res_dup = client.post(
        "/api/v1/staff/holidays",
        headers=staff_headers,
        json={"date": holiday_date, "description": "Duplicate holiday"},
    )
    assert res_dup.status_code == status.HTTP_409_CONFLICT

    # 2. Check public availability -> empty slots
    res_avail = client.get(
        f"/api/v1/availability?stylist_id=1&service_id=1&date={holiday_date}"
    )
    assert res_avail.status_code == status.HTTP_200_OK
    assert res_avail.json()["available_slots"] == []

    # 3. Customer attempts to book on the holiday -> 409 Conflict
    booking_time = f"{holiday_date}T10:00:00"
    res_book = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Holiday Customer",
            "customer_email": "holiday@example.com",
            "customer_phone": "555-9000",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": booking_time,
        },
    )
    assert res_book.status_code == status.HTTP_409_CONFLICT
    assert "closed" in res_book.json()["detail"].lower()

    # 4. Remove holiday
    res_del = client.delete(f"/api/v1/staff/holidays/{holiday_id}", headers=staff_headers)
    assert res_del.status_code == status.HTTP_204_NO_CONTENT

    # 5. Availability should now be open
    res_avail_reopened = client.get(
        f"/api/v1/availability?stylist_id=1&service_id=1&date={holiday_date}"
    )
    assert res_avail_reopened.status_code == status.HTTP_200_OK
    assert len(res_avail_reopened.json()["available_slots"]) == 16


def test_manage_token_security_idor_prevention(client):
    """A customer with an invalid or spoofed manage_token cannot cancel or reschedule another customer's booking."""
    target_dt = (datetime.now(timezone.utc) + timedelta(days=9)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    res = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "VIP Customer",
            "customer_email": "vip@example.com",
            "customer_phone": "555-8888",
            "stylist_id": 1,
            "service_id": 1,
            "start_time": target_dt.isoformat(),
        },
    )
    assert res.status_code == status.HTTP_201_CREATED
    booking = res.json()
    booking_id = booking["id"]
    valid_token = booking["manage_token"]
    assert valid_token is not None

    # Attacker tries to cancel with invalid token -> 403 Forbidden
    res_attacker_cancel = client.post(
        f"/api/v1/bookings/{booking_id}/cancel?token=forged-or-stolen-token"
    )
    assert res_attacker_cancel.status_code == status.HTTP_403_FORBIDDEN
    assert "invalid management token" in res_attacker_cancel.json()["detail"].lower()

    # Attacker tries to reschedule with invalid token -> 403 Forbidden
    new_dt = target_dt + timedelta(hours=1)
    res_attacker_resched = client.post(
        f"/api/v1/bookings/{booking_id}/reschedule",
        json={"new_start_time": new_dt.isoformat(), "manage_token": "forged-token"},
    )
    assert res_attacker_resched.status_code == status.HTTP_403_FORBIDDEN

    # Valid token cancellation succeeds -> 200 OK
    res_valid_cancel = client.post(
        f"/api/v1/bookings/{booking_id}/cancel?token={valid_token}"
    )
    assert res_valid_cancel.status_code == status.HTTP_200_OK
    assert res_valid_cancel.json()["booking"]["status"] == "CANCELLED"

