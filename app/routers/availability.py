from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import AvailabilityResponse
from app.services.availability_service import get_stylist_availability

router = APIRouter(prefix="/availability", tags=["Availability"])


@router.get("", response_model=AvailabilityResponse)
def get_availability(
    stylist_id: int = Query(..., description="ID of the stylist"),
    service_id: int = Query(..., description="ID of the service"),
    date: date = Query(..., description="Date to check availability (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
):
    return get_stylist_availability(
        db=db,
        stylist_id=stylist_id,
        service_id=service_id,
        target_date=date,
    )
