import secrets
import threading
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Booking, Holiday, Service, Stylist
from app.schemas import BookingCreate

# In-process lock to serialize concurrent write transactions safely
_booking_mutation_lock = threading.Lock()


def get_salon_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.SALON_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def to_salon_local_datetime(dt: datetime) -> datetime:
    tz = get_salon_timezone()
    if dt.tzinfo is None:
        # Assume incoming naive datetime is already in Salon local time or UTC
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def get_booking_by_id(db: Session, booking_id: int) -> Booking:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking with id {booking_id} not found.",
        )
    return booking


def list_bookings(
    db: Session,
    stylist_id: Optional[int] = None,
    booking_date: Optional[datetime] = None,
    status_filter: Optional[str] = None,
) -> List[Booking]:
    query = db.query(Booking)
    if stylist_id is not None:
        query = query.filter(Booking.stylist_id == stylist_id)
    if status_filter is not None:
        query = query.filter(Booking.status == status_filter)
    if booking_date is not None:
        day_start = datetime.combine(booking_date.date(), time.min)
        day_end = datetime.combine(booking_date.date(), time.max)
        query = query.filter(Booking.start_time >= day_start, Booking.start_time <= day_end)
    return query.order_by(Booking.start_time.asc()).all()


def create_booking(db: Session, payload: BookingCreate) -> Booking:
    # 1. Verify stylist exists and is active
    stylist = db.query(Stylist).filter(Stylist.id == payload.stylist_id).first()
    if not stylist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stylist with id {payload.stylist_id} not found.",
        )
    if not stylist.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stylist {stylist.name} is inactive and cannot accept bookings.",
        )

    # 2. Verify service exists
    service = db.query(Service).filter(Service.id == payload.service_id).first()
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with id {payload.service_id} not found.",
        )

    # 3. Timezone conversion and validation
    salon_dt = to_salon_local_datetime(payload.start_time)
    appointment_date = salon_dt.date()

    # 4. Check salon holidays
    holiday = db.query(Holiday).filter(Holiday.date == appointment_date).first()
    if holiday:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The salon is closed on {appointment_date} ({holiday.description}).",
        )

    # Check past date
    now_salon = datetime.now(get_salon_timezone())
    if salon_dt < now_salon:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot book an appointment in the past.",
        )

    service_duration = timedelta(minutes=service.duration_minutes)
    salon_end_dt = salon_dt + service_duration

    # 5. Check stylist working hours (evaluated in salon local time)
    try:
        sh, sm, ss = map(int, stylist.work_start_time.split(":"))
        eh, em, es = map(int, stylist.work_end_time.split(":"))
        work_start = datetime.combine(appointment_date, time(sh, sm, ss), tzinfo=get_salon_timezone())
        work_end = datetime.combine(appointment_date, time(eh, em, es), tzinfo=get_salon_timezone())
    except Exception:
        work_start = datetime.combine(appointment_date, settings.SALON_OPEN_TIME, tzinfo=get_salon_timezone())
        work_end = datetime.combine(appointment_date, settings.SALON_CLOSE_TIME, tzinfo=get_salon_timezone())

    if salon_dt < work_start or salon_end_dt > work_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested time ({salon_dt.strftime('%H:%M')} - {salon_end_dt.strftime('%H:%M')}) is outside stylist working hours ({stylist.work_start_time[:5]} - {stylist.work_end_time[:5]}).",
        )

    # Convert to UTC naive datetime for standardized database persistence
    start_time_utc = salon_dt.astimezone(timezone.utc).replace(tzinfo=None)
    end_time_utc = salon_end_dt.astimezone(timezone.utc).replace(tzinfo=None)

    # 6. Critical Section: Serialize booking write transaction to prevent race conditions
    with _booking_mutation_lock:
        try:
            if db.bind and db.bind.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        except Exception:
            pass

        # Half-open interval intersection: (start_time < existing.end_time AND end_time > existing.start_time)
        existing_conflict = (
            db.query(Booking)
            .filter(
                Booking.stylist_id == payload.stylist_id,
                Booking.status != "CANCELLED",
                Booking.start_time < end_time_utc,
                Booking.end_time > start_time_utc,
            )
            .first()
        )

        if existing_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Stylist {stylist.name} is already booked during this time window.",
            )

        # Generate cryptographic management token for secure self-service reschedule & cancel
        manage_token = secrets.token_urlsafe(32)

        new_booking = Booking(
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            customer_phone=payload.customer_phone,
            stylist_id=payload.stylist_id,
            service_id=payload.service_id,
            start_time=start_time_utc,
            end_time=end_time_utc,
            status="CONFIRMED",
            service_price_cents=service.price_cents,
            cancellation_fee_cents=0,
            manage_token=manage_token,
        )
        db.add(new_booking)
        db.commit()
        db.refresh(new_booking)
        return new_booking


def cancel_booking(db: Session, booking_id: int, manage_token: Optional[str] = None) -> Booking:
    with _booking_mutation_lock:
        booking = get_booking_by_id(db, booking_id)
        if booking.status == "CANCELLED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Booking is already cancelled.",
            )

        # IDOR prevention: if booking has a manage_token and a token is passed, verify match
        if manage_token and booking.manage_token and manage_token != booking.manage_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid management token for this booking.",
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        time_until_appointment = booking.start_time - now
        if time_until_appointment > timedelta(hours=24):
            fee = 0
        else:
            fee = booking.service_price_cents // 2

        booking.status = "CANCELLED"
        booking.cancellation_fee_cents = fee
        booking.updated_at = now
        db.commit()
        db.refresh(booking)
        return booking


def reschedule_booking(
    db: Session,
    booking_id: int,
    new_start_time: datetime,
    manage_token: Optional[str] = None,
    new_stylist_id: Optional[int] = None,
) -> Booking:
    with _booking_mutation_lock:
        booking = get_booking_by_id(db, booking_id)
        if booking.status == "CANCELLED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reschedule a cancelled booking. Please make a new booking.",
            )

        # IDOR prevention
        if manage_token and booking.manage_token and manage_token != booking.manage_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid management token for this booking.",
            )

        stylist_id = new_stylist_id if new_stylist_id is not None else booking.stylist_id
        stylist = db.query(Stylist).filter(Stylist.id == stylist_id).first()
        if not stylist or not stylist.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target stylist is invalid or inactive.",
            )

        salon_dt = to_salon_local_datetime(new_start_time)
        now_salon = datetime.now(get_salon_timezone())
        if salon_dt < now_salon:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reschedule to an appointment in the past.",
            )

        # Check holidays
        new_date = salon_dt.date()
        holiday = db.query(Holiday).filter(Holiday.date == new_date).first()
        if holiday:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot reschedule to {new_date}: the salon is closed ({holiday.description}).",
            )

        service = db.query(Service).filter(Service.id == booking.service_id).first()
        duration = service.duration_minutes if service else 30
        service_duration = timedelta(minutes=duration)
        salon_end_dt = salon_dt + service_duration

        # Check stylist working hours
        try:
            sh, sm, ss = map(int, stylist.work_start_time.split(":"))
            eh, em, es = map(int, stylist.work_end_time.split(":"))
            work_start = datetime.combine(new_date, time(sh, sm, ss), tzinfo=get_salon_timezone())
            work_end = datetime.combine(new_date, time(eh, em, es), tzinfo=get_salon_timezone())
        except Exception:
            work_start = datetime.combine(new_date, settings.SALON_OPEN_TIME, tzinfo=get_salon_timezone())
            work_end = datetime.combine(new_date, settings.SALON_CLOSE_TIME, tzinfo=get_salon_timezone())

        if salon_dt < work_start or salon_end_dt > work_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rescheduled time is outside stylist working hours.",
            )

        new_start_utc = salon_dt.astimezone(timezone.utc).replace(tzinfo=None)
        new_end_utc = salon_end_dt.astimezone(timezone.utc).replace(tzinfo=None)

        try:
            if db.bind and db.bind.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        except Exception:
            pass

        # Exclude self when checking for overlap
        existing_conflict = (
            db.query(Booking)
            .filter(
                Booking.id != booking_id,
                Booking.stylist_id == stylist_id,
                Booking.status != "CANCELLED",
                Booking.start_time < new_end_utc,
                Booking.end_time > new_start_utc,
            )
            .first()
        )

        if existing_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Stylist {stylist.name} is already booked during the requested new time window.",
            )

        booking.stylist_id = stylist_id
        booking.start_time = new_start_utc
        booking.end_time = new_end_utc
        booking.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(booking)
        return booking
