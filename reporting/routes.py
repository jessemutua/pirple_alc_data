# reporting/routes.py
"""
Manufacturer dashboard API.

Every route except login requires a manufacturer token, and scope comes from
that token, never from a parameter the caller supplies. There is no way to
ask this API for someone else's data.
"""
import csv
import io
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.ratelimit import LOGIN_LIMIT, limiter
from core.security import verify_password
from reporting import service
from reporting.models import ManufacturerUser
from reporting.query import QuerySpec, facets, run_query
from reporting.security import (
    ManufacturerContext,
    create_manufacturer_token,
    get_current_manufacturer,
    get_db,
)
from reporting.service import DateRange, resolve_range

router = APIRouter(prefix="/manufacturer", tags=["manufacturer"])

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


def date_range(
    date_from: Optional[date] = Query(None, description="Local start date, inclusive"),
    date_to: Optional[date] = Query(None, description="Local end date, inclusive"),
    days: Optional[int] = Query(
        None, ge=1, le=service.MAX_DAYS, description="Fallback rolling window"
    ),
) -> DateRange:
    """
    One reporting period per request, interpreted identically everywhere.

    `days` is kept for older clients and will be removed once the dashboard
    sends explicit dates.
    """
    return resolve_range(date_from, date_to, days)


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


@router.post("/auth/login")
@limiter.limit(LOGIN_LIMIT)
def login(request: Request, payload: LoginPayload, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()

    user = db.scalar(select(ManufacturerUser).where(ManufacturerUser.email == email))

    # Same response whether the account is missing, wrong-password or
    # deactivated: do not confirm which emails exist.
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
    rng: DateRange = Depends(date_range),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return service.summary(db, context.manufacturer_id, rng)


@router.get("/timeline")
def get_timeline(
    rng: DateRange = Depends(date_range),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {
        "period": rng.as_dict(),
        "points": service.timeline(db, context.manufacturer_id, rng),
    }


@router.get("/brands")
def get_brands(
    rng: DateRange = Depends(date_range),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {
        "period": rng.as_dict(),
        "brands": service.brands(db, context.manufacturer_id, rng),
    }


@router.get("/map")
def get_map(
    rng: DateRange = Depends(date_range),
    min_scans: int = Query(1, ge=1, le=100),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {
        "period": rng.as_dict(),
        "points": service.map_points(db, context.manufacturer_id, rng, min_scans),
    }


@router.get("/flagged")
def get_flagged(
    rng: DateRange = Depends(date_range),
    limit: int = Query(25, ge=1, le=200),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {
        "period": rng.as_dict(),
        "locations": service.flagged_locations(db, context.manufacturer_id, rng, limit),
    }


@router.get("/benchmark")
def get_benchmark(
    rng: DateRange = Depends(date_range),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    return {
        "period": rng.as_dict(),
        "categories": service.category_benchmark(db, context.manufacturer_id, rng),
    }


@router.get("/activity")
def get_activity(
    since: Optional[datetime] = Query(
        None, description="Return only scans newer than this instant"
    ),
    limit: int = Query(50, ge=1, le=200),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    """
    Newest scans, for the live window.

    Always means now, so it deliberately ignores the reporting date range.
    """
    events = service.recent_activity(db, context.manufacturer_id, since, limit)
    return {
        "timezone": service.REPORT_TZ,
        "server_time": datetime.now(service.REPORT_ZONE).isoformat(),
        "count": len(events),
        "events": events,
    }


@router.get("/facets")
def get_facets(
    days: int = Query(90, ge=1, le=365),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    """Filter options drawn from this manufacturer's own data."""
    return facets(db, context.manufacturer_id, days)


@router.post("/query")
def post_query(
    spec: QuerySpec,
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    """
    Group and filter scan data on any whitelisted dimension.

    Scope comes from the token. Unknown dimensions, measures or filters are
    dropped rather than passed through, so nothing from the body reaches SQL
    as text.
    """
    return run_query(db, context.manufacturer_id, spec)


@router.get("/export.csv")
def export_csv(
    rng: DateRange = Depends(date_range),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    """Streamed: a busy manufacturer over 90 days is tens of thousands of rows."""

    def generate():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)

        writer.writeheader()
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        for row in service.export_rows(db, context.manufacturer_id, rng):
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