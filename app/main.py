from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Service, Stylist
from app.routers import availability, bookings, catalog, staff


def init_db_and_seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Seed default stylists if none exist
        if db.query(Stylist).count() == 0:
            default_stylists = [
                Stylist(name="Alice Smith", work_start_time="09:00:00", work_end_time="17:00:00", is_active=True),
                Stylist(name="Bob Jones", work_start_time="09:00:00", work_end_time="17:00:00", is_active=True),
            ]
            db.add_all(default_stylists)
            db.commit()

        # Seed default services if none exist
        if db.query(Service).count() == 0:
            default_services = [
                Service(name="Haircut", duration_minutes=30, price_cents=3500),
                Service(name="Coloring", duration_minutes=120, price_cents=12000),
                Service(name="Beard Trim", duration_minutes=15, price_cents=2000),
            ]
            db.add_all(default_services)
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db_and_seed()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for online salon appointment bookings.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API v1 Routers
api_v1_prefix = "/api/v1"
app.include_router(catalog.router, prefix=api_v1_prefix)
app.include_router(availability.router, prefix=api_v1_prefix)
app.include_router(bookings.router, prefix=api_v1_prefix)
app.include_router(staff.router, prefix=api_v1_prefix)


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
