import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import Service, Stylist


@pytest.fixture(scope="function")
def test_db():
    # Use a temporary SQLite file to accurately test SQLite WAL, transactions, and concurrency
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    @event.listens_for(test_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.close()

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    db = TestingSessionLocal()
    try:
        # Seed test stylists
        s1 = Stylist(name="Alice Smith", work_start_time="09:00:00", work_end_time="17:00:00", is_active=True)
        s2 = Stylist(name="Bob Jones", work_start_time="09:00:00", work_end_time="17:00:00", is_active=True)
        s3 = Stylist(name="Inactive Stylist", work_start_time="09:00:00", work_end_time="17:00:00", is_active=False)
        db.add_all([s1, s2, s3])

        # Seed test services
        srv1 = Service(name="Haircut", duration_minutes=30, price_cents=3500)
        srv2 = Service(name="Coloring", duration_minutes=120, price_cents=12000)
        srv3 = Service(name="Beard Trim", duration_minutes=15, price_cents=2000)
        db.add_all([srv1, srv2, srv3])
        db.commit()

        yield {
            "db": db,
            "session_factory": TestingSessionLocal,
            "engine": test_engine,
            "db_path": db_path,
        }
    finally:
        db.close()
        test_engine.dispose()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        db = test_db["session_factory"]()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def staff_headers():
    return {"X-API-Key": settings.STAFF_API_KEY}
