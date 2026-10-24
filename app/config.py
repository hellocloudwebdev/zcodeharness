import os
from datetime import time
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Salon Booking Backend"
    ENVIRONMENT: str = "production"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./salon.db")
    STAFF_API_KEY: str = os.getenv("STAFF_API_KEY", "dev-staff-key-change-in-production")
    SALON_TIMEZONE: str = os.getenv("SALON_TIMEZONE", "UTC")
    SALON_OPEN_TIME: time = time(9, 0)
    SALON_CLOSE_TIME: time = time(17, 0)
    DEFAULT_SLOT_STEP_MINUTES: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
