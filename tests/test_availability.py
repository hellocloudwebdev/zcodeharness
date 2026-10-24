from datetime import date, timedelta
from fastapi import status


def test_list_services_and_stylists_public(client):
    """Catalog endpoints must be public and return seeded services and stylists."""
    res_services = client.get("/api/v1/catalog/services")
    assert res_services.status_code == status.HTTP_200_OK
    services = res_services.json()
    assert len(services) >= 3
    assert any(s["name"] == "Haircut" for s in services)

    res_stylists = client.get("/api/v1/catalog/stylists")
    assert res_stylists.status_code == status.HTTP_200_OK
    stylists = res_stylists.json()
    assert len(stylists) == 2  # Only active stylists (Alice, Bob)
    assert all(s["is_active"] is True for s in stylists)


def test_availability_full_day_no_bookings(client):
    """When no bookings exist, all slots between 09:00 and 17:00 should be available."""
    target_date = (date.today() + timedelta(days=5)).isoformat()
    res = client.get(
        f"/api/v1/availability?stylist_id=1&service_id=1&date={target_date}"
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    slots = data["available_slots"]
    # 09:00 to 17:00 in 30-min increments: 16 slots (09:00, 09:30, ..., 16:30)
    assert len(slots) == 16
    assert slots[0]["start_time"].endswith("09:00:00")
    assert slots[-1]["start_time"].endswith("16:30:00")


def test_availability_excludes_booked_slots(client):
    """Booked slots must be excluded from available slots list."""
    target_date = date.today() + timedelta(days=6)
    # Book 10:00 - 10:30
    booking_time = f"{target_date.isoformat()}T10:00:00"
    booking_res = client.post(
        "/api/v1/bookings",
        json={
            "customer_name": "Charlie Brown",
            "customer_email": "charlie@example.com",
            "customer_phone": "555-12345",
            "stylist_id": 1,
            "service_id": 1,  # 30-min haircut
            "start_time": booking_time,
        },
    )
    assert booking_res.status_code == status.HTTP_201_CREATED

    # Query availability for that day
    res = client.get(
        f"/api/v1/availability?stylist_id=1&service_id=1&date={target_date.isoformat()}"
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    slots = data["available_slots"]
    start_times = [s["start_time"] for s in slots]
    assert not any("10:00:00" in t for t in start_times)
    assert any("09:30:00" in t for t in start_times)
    assert any("10:30:00" in t for t in start_times)
    assert len(slots) == 15  # 16 - 1 = 15 slots


def test_availability_service_duration_respected(client):
    """A 120-min service (Coloring) must only offer slots that end before closing (17:00)."""
    target_date = (date.today() + timedelta(days=7)).isoformat()
    res = client.get(
        f"/api/v1/availability?stylist_id=1&service_id=2&date={target_date}"
    )
    assert res.status_code == status.HTTP_200_OK
    slots = res.json()["available_slots"]
    # 120 min duration: Last slot starts at 15:00 and ends at 17:00
    last_slot = slots[-1]
    assert last_slot["start_time"].endswith("15:00:00")
    assert last_slot["end_time"].endswith("17:00:00")


def test_availability_nonexistent_stylist_or_service_returns_404(client):
    target_date = (date.today() + timedelta(days=8)).isoformat()
    # Stylist 999 doesn't exist
    res1 = client.get(
        f"/api/v1/availability?stylist_id=999&service_id=1&date={target_date}"
    )
    assert res1.status_code == status.HTTP_404_NOT_FOUND

    # Service 999 doesn't exist
    res2 = client.get(
        f"/api/v1/availability?stylist_id=1&service_id=999&date={target_date}"
    )
    assert res2.status_code == status.HTTP_404_NOT_FOUND


def test_availability_inactive_stylist_returns_400(client):
    target_date = (date.today() + timedelta(days=8)).isoformat()
    # Stylist 3 is inactive in seed data
    res = client.get(
        f"/api/v1/availability?stylist_id=3&service_id=1&date={target_date}"
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "inactive" in res.json()["detail"].lower()
