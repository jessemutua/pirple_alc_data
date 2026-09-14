# reporting/security.py
"""
Authentication for manufacturer dashboard accounts.

Separate from consumer auth: tokens carry typ="manufacturer" and the
manufacturer id, and are rejected anywhere that claim is missing. A consumer
app token therefore cannot reach a reporting endpoint.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from core.config import JWT_ALGORITHM, JWT_SECRET
from core.database import SessionLocal
from products.models import Manufacturer
from reporting.models import ManufacturerUser

TOKEN_TYPE = "manufacturer"

# Shorter than the consumer token: this is commercial data, and a leaked
# dashboard token should not stay valid for days.
EXPIRE_HOURS = int(os.getenv("MANUFACTURER_JWT_EXPIRE_HOURS", "12"))

bearer = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@dataclass
class ManufacturerContext:
    """Everything a reporting route needs about the caller."""

    user: ManufacturerUser
    manufacturer: Manufacturer

    @property
    def manufacturer_id(self) -> str:
        return self.manufacturer.id

    @property
    def is_admin(self) -> bool:
        return self.user.role == "admin"


def create_manufacturer_token(user: ManufacturerUser) -> str:
    payload = {
        "sub": str(user.id),
        "typ": TOKEN_TYPE,
        "mid": str(user.manufacturer_id),
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def get_current_manufacturer(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> ManufacturerContext:
    """
    Resolve the caller to a manufacturer account.

    Account state is re-read on every request rather than trusted from the
    token, so revoking a user takes effect immediately.
    """
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise _unauthorized("Invalid or expired token")

    if payload.get("typ") != TOKEN_TYPE:
        # A consumer token, or anything else. Never accepted here.
        raise _unauthorized("Not a manufacturer token")

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise _unauthorized("Invalid token")

    user = db.get(ManufacturerUser, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Account is not active")

    manufacturer = db.get(Manufacturer, user.manufacturer_id)
    if manufacturer is None:
        raise _unauthorized("Manufacturer not found")

    return ManufacturerContext(user=user, manufacturer=manufacturer)


def require_admin(
    context: ManufacturerContext = Depends(get_current_manufacturer),
) -> ManufacturerContext:
    """For endpoints that manage users rather than read reports."""
    if not context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return context