from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import (
    BookingCreate,
    BookingOut,
    CancelBookingResponse,
    RescheduleBookingRequest,
)
from app.services.booking_service import (
    cancel_booking,
    create_booking,
    get_booking_by_id,
    reschedule_booking,
)

router = APIRouter(prefix="/bookings", tags=["Bookings"])


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def book_appointment(payload: BookingCreate, db: Session = Depends(get_db)):
    return create_booking(db, payload)


@router.get("/{booking_id}", response_model=BookingOut)
def read_booking(booking_id: int, db: Session = Depends(get_db)):
    return get_booking_by_id(db, booking_id)


@router.post("/{booking_id}/cancel", response_model=CancelBookingResponse)
def customer_cancel_booking(
    booking_id: int,
    token: Optional[str] = Query(None, description="Cryptographic management token for IDOR protection"),
    db: Session = Depends(get_db),
):
    cancelled = cancel_booking(db, booking_id, manage_token=token)
    return CancelBookingResponse(
        message="Booking successfully cancelled.",
        cancellation_fee_cents=cancelled.cancellation_fee_cents,
        booking=BookingOut.model_validate(cancelled),
    )


@router.post("/{booking_id}/reschedule", response_model=BookingOut)
def customer_reschedule_booking(
    booking_id: int,
    payload: RescheduleBookingRequest,
    db: Session = Depends(get_db),
):
    return reschedule_booking(
        db,
        booking_id,
        new_start_time=payload.new_start_time,
        manage_token=payload.manage_token,
    )
