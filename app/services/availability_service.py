from datetime import date, datetime, time, timedelta
from typing import List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Booking, Holiday, Service, Stylist
from app.schemas import AvailabilityResponse, SlotOut


def get_stylist_availability(
    db: Session,
    stylist_id: int,
    service_id: int,
    target_date: date,
    step_minutes: int = 30,
) -> AvailabilityResponse:
    # 1. Verify stylist
    stylist = db.query(Stylist).filter(Stylist.id == stylist_id).first()
    if not stylist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stylist with id {stylist_id} not found.",
        )
    if not stylist.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stylist {stylist.name} is currently inactive.",
        )

    # 2. Verify service
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with id {service_id} not found.",
        )

    # 3. Check for salon holidays
    holiday = db.query(Holiday).filter(Holiday.date == target_date).first()
    if holiday:
        # Salon is closed on holidays
        return AvailabilityResponse(
            stylist_id=stylist_id,
            date=target_date,
            service_id=service_id,
            service_duration_minutes=service.duration_minutes,
            available_slots=[],
        )

    # 4. Determine working hours for the date
    try:
        sh, sm, ss = map(int, stylist.work_start_time.split(":"))
        eh, em, es = map(int, stylist.work_end_time.split(":"))
        work_start = datetime.combine(target_date, time(sh, sm, ss))
        work_end = datetime.combine(target_date, time(eh, em, es))
    except Exception:
        work_start = datetime.combine(target_date, settings.SALON_OPEN_TIME)
        work_end = datetime.combine(target_date, settings.SALON_CLOSE_TIME)

    # 5. Fetch all active bookings on this date for the stylist
    # Day boundary
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)

    existing_bookings = (
        db.query(Booking)
        .filter(
            Booking.stylist_id == stylist_id,
            Booking.status != "CANCELLED",
            Booking.start_time >= day_start,
            Booking.start_time <= day_end,
        )
        .all()
    )

    # 6. Generate candidate slots
    service_duration = timedelta(minutes=service.duration_minutes)
    slot_step = timedelta(minutes=step_minutes)
    available_slots: List[SlotOut] = []

    current_slot_start = work_start
    while current_slot_start + service_duration <= work_end:
        current_slot_end = current_slot_start + service_duration

        # Half-open interval check: does [current_slot_start, current_slot_end) overlap with any [b.start_time, b.end_time)?
        # Two intervals [S1, E1) and [S2, E2) overlap iff (S1 < E2 and E1 > S2)
        has_overlap = False
        for b in existing_bookings:
            if current_slot_start < b.end_time and current_slot_end > b.start_time:
                has_overlap = True
                break

        if not has_overlap:
            available_slots.append(
                SlotOut(
                    start_time=current_slot_start,
                    end_time=current_slot_end,
                )
            )

        current_slot_start += slot_step

    return AvailabilityResponse(
        stylist_id=stylist_id,
        date=target_date,
        service_id=service_id,
        service_duration_minutes=service.duration_minutes,
        available_slots=available_slots,
    )
