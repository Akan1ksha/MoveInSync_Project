"""
JWT creation and verification.
Identity (company_id, employee_id) is ALWAYS taken from the token — never
from request body or model output.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends

from app.core.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer()


def create_token(company_id: str, employee_id: str, role: str = "employee") -> str:
    """
    Mint a signed JWT.  Called only by /auth/token (dev helper) or tests.
    """
    payload = {
        "sub": employee_id,
        "company_id": company_id,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    """
    Decode and validate a JWT.  Raises HTTP 401 on any failure.
    Returns the full payload dict.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}")


def get_current_identity(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    FastAPI dependency — inject into every protected route.
    Returns {"employee_id": ..., "company_id": ..., "role": ...}
    """
    return verify_token(credentials.credentials)
