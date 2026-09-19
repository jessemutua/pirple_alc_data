# drinks/scan_routes.py
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.geo import county_for
from core.security import get_current_user_id
from drinks.scan_models import ScanEvent, uuid_str
from products.adapters import (
    REGISTRY_REGISTERED,
    REGISTRY_UNREACHABLE,
    SERIAL_NOT_ISSUED,
    SERIAL_UNKNOWN,
    lookup_product,
    to_gtin14,
    verify_serial,
)
from products.models import Manufacturer, ProductSerial
from verification.engine import (
    STATUS_INVALID,
    STATUS_UNKNOWN,
    STATUS_VALID,
    ScanContext,
    evaluate,
)

router = APIRouter(prefix="/products", tags=["scan"])

# A GS1 DataMatrix payload is a few dozen characters in practice. The cap is
# generous enough for element strings and Digital Link URLs, and small enough
# that the raw scan cannot be used to push arbitrary content into storage or
# into a manufacturer's browser.
MAX_BARCODE_LEN = 512

# GS1 Application Identifier 21 is variable length up to 20 characters. The
# character set is narrower than GS1's own set 82: manufacturers control what
# they print, so the conservative set costs nothing.
SERIAL_PATTERN = r"^[A-Za-z0-9\-_./]{1,20}$"

# 8 for EAN-8 through 14 for ITF-14. Everything normalises to 14 downstream.
GTIN_PATTERN = r"^\d{8,14}$"

# You can only retire a seal you are holding, and you were holding it when
# you scanned it. This stops anyone burning codes they have never seen.
RETIRE_WINDOW_HOURS = 12


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ScanLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    barcode: str = Field(min_length=1, max_length=MAX_BARCODE_LEN)
    gtin: str = Field(min_length=8, max_length=14, pattern=GTIN_PATTERN)
    serial: Optional[str] = Field(default=None, max_length=20, pattern=SERIAL_PATTERN)
    lat: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    lng: Optional[float] = Field(default=None, ge=-180.0, le=180.0)

    @field_validator("serial", mode="before")
    @classmethod
    def empty_serial_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class RetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    gtin: str = Field(min_length=8, max_length=14, pattern=GTIN_PATTERN)
    serial: str = Field(min_length=1, max_length=20, pattern=SERIAL_PATTERN)
    lat: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    lng: Optional[float] = Field(default=None, ge=-180.0, le=180.0)


def perform_scan(
    db: Session,
    current_user_id: str,
    barcode: str,
    gtin: str,
    serial: Optional[str],
    lat: Optional[float],
    lng: Optional[float],
) -> dict:
    """
    Registry, then ledger, then the seal's own history.

    Every branch writes a scan event, including the failures, because a
    fabricated code found in a bar is exactly what the manufacturer wants
    to know about.
    """
    # Normalise once. Lookup, ledger and reporting all use the 14-digit form
    # so the parser and the catalogue can never disagree.
    gtin14 = to_gtin14(gtin)

    registry_result, product, raw_response = lookup_product(db, gtin)

    serial_result = SERIAL_UNKNOWN
    auth_status = STATUS_UNKNOWN
    auth_reason = None
    facts: dict = {}
    features: dict = {}
    first_scan_at = prior_scan_at = prior_scan_user_id = None
    manufacturer = None

    if registry_result != REGISTRY_REGISTERED:
        if registry_result == REGISTRY_UNREACHABLE:
            # We could not check. Say so, never imply a pass.
            auth_reason = "the producer's records are unavailable right now"
        else:
            auth_status = STATUS_INVALID
            auth_reason = "this barcode is not registered to any manufacturer"
    else:
        manufacturer = db.get(Manufacturer, product.manufacturer_id)
        serial_result, serial_reason = verify_serial(db, product, serial)

        if serial_result == SERIAL_NOT_ISSUED:
            auth_status = STATUS_INVALID
            auth_reason = "this seal code was not issued for this product"

        elif serial_result == SERIAL_UNKNOWN:
            # Either the label carries no unique code, or we could not reach
            # the manufacturer's own system. Neither is a pass.
            auth_status = STATUS_UNKNOWN
            auth_reason = (
                "this label carries no unique code"
                if not serial
                else serial_reason
            )

        else:
            verdict = evaluate(
                db,
                ScanContext(
                    gtin14=gtin14,
                    serial=serial,
                    user_id=current_user_id,
                    lat=lat,
                    lng=lng,
                ),
            )
            auth_status = verdict.status
            auth_reason = verdict.reason
            facts = verdict.facts
            features = verdict.features
            first_scan_at = verdict.first_scan_at
            prior_scan_at = verdict.prior_scan_at
            prior_scan_user_id = verdict.prior_scan_user_id

    county = county_for(lat, lng)

    event = ScanEvent(
        id=uuid_str(),
        user_id=current_user_id,
        barcode_raw=barcode,
        gtin=gtin14,
        serial=serial,
        registry_result=registry_result,
        serial_result=serial_result,
        manufacturer_raw_response=raw_response,
        manufacturer_id=product.manufacturer_id if product else None,
        brand=product.brand if product else None,
        category=product.category if product else None,
        county=county,
        first_scan_at=first_scan_at,
        prior_scan_at=prior_scan_at,
        prior_scan_user_id=prior_scan_user_id,
        combined_auth_status=auth_status,
        auth_reason=auth_reason,
        risk_score=100.0 if auth_status == STATUS_INVALID else 0.0,
        risk_reasons=[auth_reason] if auth_reason else None,
        scan_features=features or None,
        location_lat=lat,
        location_lng=lng,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    # The product name is established fact only when the seal checks out. A
    # code that was never issued usually means the barcode was copied too,
    # so naming the product there asserts something we do not know.
    seal_ok = auth_status == STATUS_VALID

    return {
        "scan_event_id": event.id,
        "status": auth_status,
        "auth_status": auth_status,  # kept until the app update lands
        "auth_reason": auth_reason,
        "facts": facts,
        "product": (
            {
                "brand": product.brand,
                "name": product.product_name,
                "manufacturer": manufacturer.name if manufacturer else None,
            }
            if product
            else None
        ),
        "product_verified": seal_ok,
        "can_retire": seal_ok and bool(serial),
        "scanned_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.post("/lookup")
def scan_lookup(
    payload: ScanLookupRequest,
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return perform_scan(
        db=db,
        current_user_id=current_user_id,
        barcode=payload.barcode,
        gtin=payload.gtin,
        serial=payload.serial,
        lat=payload.lat,
        lng=payload.lng,
    )


@router.post("/retire")
def retire_seal(
    payload: RetireRequest,
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    The bottle was opened, so this seal no longer exists in the world.

    One way only. A broken seal cannot be unbroken, and an undo is the first
    thing a counterfeiter would reach for.
    """
    gtin14 = to_gtin14(payload.gtin)
    row = db.get(ProductSerial, (gtin14, payload.serial))

    if row is None:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "No such seal code")

    # You can only retire a seal you were holding, and you were holding it
    # when you scanned it.
    since = datetime.now(timezone.utc) - timedelta(hours=RETIRE_WINDOW_HOURS)
    held = (
        db.query(ScanEvent)
        .filter(ScanEvent.serial == payload.serial)
        .filter(ScanEvent.gtin == gtin14)
        .filter(ScanEvent.user_id == current_user_id)
        .filter(ScanEvent.created_at >= since)
        .first()
    )
    if held is None:
        raise HTTPException(
            http.HTTP_403_FORBIDDEN,
            "Scan this bottle before marking it opened",
        )

    if row.retired_at is not None:
        # Already done. Saying so is friendlier than an error, and repeating
        # the action must never move the timestamp.
        return {
            "retired": True,
            "retired_at": row.retired_at.isoformat(),
            "already": True,
        }

    row.retired_at = datetime.now(timezone.utc)
    row.retired_by = current_user_id
    row.retired_lat = payload.lat
    row.retired_lng = payload.lng
    db.commit()

    return {"retired": True, "retired_at": row.retired_at.isoformat(), "already": False}


@router.get("/lookup", deprecated=True)
def scan_lookup_legacy(
    barcode: str = Query(..., min_length=1, max_length=MAX_BARCODE_LEN),
    gtin: str = Query(..., min_length=8, max_length=14, pattern=GTIN_PATTERN),
    serial: Optional[str] = Query(None, max_length=20, pattern=SERIAL_PATTERN),
    lat: Optional[float] = Query(None, ge=-90.0, le=90.0),
    lng: Optional[float] = Query(None, ge=-180.0, le=180.0),
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Deprecated. A scan writes a row, so it must not be a GET: clients and
    proxies retry GETs automatically, which duplicates scan events.
    """
    return perform_scan(
        db=db,
        current_user_id=current_user_id,
        barcode=barcode,
        gtin=gtin,
        serial=serial,
        lat=lat,
        lng=lng,
    )