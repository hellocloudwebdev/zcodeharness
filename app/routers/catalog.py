from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Service, Stylist
from app.schemas import ServiceOut, StylistOut

router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.get("/services", response_model=List[ServiceOut])
def list_services(db: Session = Depends(get_db)):
    return db.query(Service).order_by(Service.id.asc()).all()


@router.get("/stylists", response_model=List[StylistOut])
def list_stylists(db: Session = Depends(get_db)):
    return db.query(Stylist).filter(Stylist.is_active == True).order_by(Stylist.id.asc()).all()
