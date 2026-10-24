from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Stylist(Base):
    __tablename__ = "stylists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    work_start_time = Column(String(8), nullable=False, default="09:00:00")
    work_end_time = Column(String(8), nullable=False, default="17:00:00")
    is_active = Column(Boolean, nullable=False, default=True)

    bookings = relationship("Booking", back_populates="stylist")


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    price_cents = Column(Integer, nullable=False)

    bookings = relationship("Booking", back_populates="service")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String(100), nullable=False)
    customer_email = Column(String(255), nullable=False)
    customer_phone = Column(String(50), nullable=False)

    stylist_id = Column(Integer, ForeignKey("stylists.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)

    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=False, index=True)

    status = Column(String(20), nullable=False, default="CONFIRMED")
    service_price_cents = Column(Integer, nullable=False)
    cancellation_fee_cents = Column(Integer, nullable=False, default=0)

    manage_token = Column(String(64), nullable=True, index=True)

    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    stylist = relationship("Stylist", back_populates="bookings")
    service = relationship("Service", back_populates="bookings")


Index(
    "ix_bookings_stylist_time",
    Booking.stylist_id,
    Booking.start_time,
    Booking.end_time,
)


class Holiday(Base):
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=False)
