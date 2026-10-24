from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.auth import require_staff_api_key
from app.database import get_db
from app.models import Holiday
from app.schemas import BookingOut, HolidayCreate, HolidayOut
from app.services.booking_service import list_bookings

router = APIRouter(prefix="/staff", tags=["Staff"])


@router.get(
    "/bookings",
    response_model=List[BookingOut],
    dependencies=[Depends(require_staff_api_key)],
)
def staff_list_bookings(
    stylist_id: Optional[int] = Query(None, description="Filter by stylist ID"),
    booking_date: Optional[date] = Query(None, description="Filter by booking date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Filter by status (CONFIRMED, CANCELLED)"),
    db: Session = Depends(get_db),
):
    dt = datetime.combine(booking_date, datetime.min.time()) if booking_date else None
    return list_bookings(db, stylist_id=stylist_id, booking_date=dt, status_filter=status)


@router.post(
    "/holidays",
    response_model=HolidayOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_staff_api_key)],
)
def create_holiday(payload: HolidayCreate, db: Session = Depends(get_db)):
    existing = db.query(Holiday).filter(Holiday.date == payload.date).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Holiday on {payload.date} already exists.",
        )
    holiday = Holiday(date=payload.date, description=payload.description)
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday


@router.get(
    "/holidays",
    response_model=List[HolidayOut],
    dependencies=[Depends(require_staff_api_key)],
)
def list_all_holidays(db: Session = Depends(get_db)):
    return db.query(Holiday).order_by(Holiday.date.asc()).all()


@router.delete(
    "/holidays/{holiday_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_staff_api_key)],
)
def remove_holiday(holiday_id: int, db: Session = Depends(get_db)):
    holiday = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if not holiday:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Holiday with id {holiday_id} not found.",
        )
    db.delete(holiday)
    db.commit()
    return None
