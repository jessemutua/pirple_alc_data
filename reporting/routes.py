# reporting/routes.py
"""
Manufacturer dashboard API.

Every route except login requires a manufacturer token, and scope comes from
that token — never from a parameter the caller supplies. There is no way to
ask this API for someone else's data.
"""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.security import verify_password
from reporting import service
from reporting.models import ManufacturerUser
from reporting.security import (
    ManufacturerContext,
    create_manufacturer_token,
    get_current_manufacturer,
    get_db,
)

router = APIRouter(prefix="/manufacturer", tags=["manufacturer"])

# Bounded so a single request can't ask for a full-table scan.
DaysParam = Query(30, ge=1, le=365, description="Reporting window in days")

# Must match the keys yielded by service.export_rows.
EXPORT_COLUMNS = [
    "scanned_at",
    "gtin",
    "brand",
    "category",
    "serial",
    "registry_result",
    "serial_result",
    "status",
    "reason",
    "unit_price",
    "currency",
    "lat",
    "lng",
]


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


@router.post("/auth/login")
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()

    user = db.scalar(select(ManufacturerUser).where(ManufacturerUser.email == email))

    # Same response whether the account is missing, wrong-password or
    # deactivated — don't confirm which emails exist.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    return {
        "access_token": create_manufacturer_token(user),
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
    }


@router.get("/me")
def me(context: ManufacturerContext = Depends(get_current_manufacturer)):
    return {
        "user": {
            "id": context.user.id,
            "email": context.user.email,
            "full_name": context.user.full_name,
            "role": context.user.role,
        },
        "manufacturer": {
            "id": context.manufacturer.id,
            "name": context.manufacturer.name,
            "slug": context.manufacturer.slug,
        },
    }


@router.get("/summary")
def get_summary(
    days: int = DaysParam,
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return service.summary(db, context.manufacturer_id, days)


@router.get("/timeline")
def get_timeline(
    days: int = DaysParam,
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {"days": days, "points": service.timeline(db, context.manufacturer_id, days)}


@router.get("/brands")
def get_brands(
    days: int = DaysParam,
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {"days": days, "brands": service.brands(db, context.manufacturer_id, days)}


@router.get("/map")
def get_map(
    days: int = DaysParam,
    min_scans: int = Query(1, ge=1, le=100),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {
        "days": days,
        "points": service.map_points(db, context.manufacturer_id, days, min_scans),
    }


@router.get("/flagged")
def get_flagged(
    days: int = DaysParam,
    limit: int = Query(25, ge=1, le=200),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {
        "days": days,
        "locations": service.flagged_locations(db, context.manufacturer_id, days, limit),
    }


@router.get("/benchmark")
def get_benchmark(
    days: int = DaysParam,
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {
        "days": days,
        "categories": service.category_benchmark(db, context.manufacturer_id, days),
    }


@router.get("/export.csv")
def export_csv(
    days: int = DaysParam,
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    """Streamed — a busy manufacturer over 90 days is tens of thousands of rows."""

    def generate():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)

        writer.writeheader()
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        for row in service.export_rows(db, context.manufacturer_id, days):
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"limi-scans-{context.manufacturer.slug}-{stamp}.csv"

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )