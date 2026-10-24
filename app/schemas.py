from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class StylistBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    work_start_time: str = Field("09:00:00", pattern=r"^\d{2}:\d{2}:\d{2}$")
    work_end_time: str = Field("17:00:00", pattern=r"^\d{2}:\d{2}:\d{2}$")
    is_active: bool = True


class StylistOut(StylistBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ServiceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    duration_minutes: int = Field(..., gt=0, le=480)
    price_cents: int = Field(..., ge=0)


class ServiceOut(ServiceBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class BookingCreate(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=100)
    customer_email: EmailStr
    customer_phone: str = Field(..., min_length=5, max_length=50)
    stylist_id: int = Field(..., gt=0)
    service_id: int = Field(..., gt=0)
    start_time: datetime

    @field_validator("customer_name")
    @classmethod
    def validate_name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Customer name cannot be whitespace only")
        return v.strip()


class BookingOut(BaseModel):
    id: int
    customer_name: str
    customer_email: str
    customer_phone: str
    stylist_id: int
    service_id: int
    start_time: datetime
    end_time: datetime
    status: str
    service_price_cents: int
    cancellation_fee_cents: int
    manage_token: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SlotOut(BaseModel):
    start_time: datetime
    end_time: datetime


class AvailabilityResponse(BaseModel):
    stylist_id: int
    date: date
    service_id: int
    service_duration_minutes: int
    available_slots: List[SlotOut]


class CancelBookingResponse(BaseModel):
    message: str
    cancellation_fee_cents: int
    booking: BookingOut


class RescheduleBookingRequest(BaseModel):
    new_start_time: datetime
    manage_token: Optional[str] = None


class HolidayCreate(BaseModel):
    date: date
    description: str = Field(..., min_length=1, max_length=255)


class HolidayOut(BaseModel):
    id: int
    date: date
    description: str
    model_config = ConfigDict(from_attributes=True)
