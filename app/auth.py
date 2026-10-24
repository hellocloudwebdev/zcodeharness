from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_staff_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing staff API key. Provide the 'X-API-Key' header.",
        )
    if api_key != settings.STAFF_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid staff API key.",
        )
    return api_key
