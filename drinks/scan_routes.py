# drinks/scan_routes.py
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.geo import county_for
from core.security import get_current_user_id
from drinks.scan_models import ScanEvent, uuid_str
from drinks.scan_reuse import check_reuse
from products.adapters import (
    REGISTRY_REGISTERED,
    REGISTRY_UNREACHABLE,
    SERIAL_NOT_ISSUED,
    SERIAL_UNKNOWN,
    lookup_product,
    to_gtin14,
    verify_serial,
)
from products.models import Manufacturer

router = APIRouter(prefix="/products", tags=["scan"])

STATUS_VERIFIED = "verified"
STATUS_SUSPICIOUS = "suspicious"
STATUS_UNKNOWN = "unknown"

# A GS1 DataMatrix payload is a few dozen characters in practice. The cap is
# generous enough for element strings and Digital Link URLs, and small enough
# that the raw scan cannot be used to push arbitrary content into storage or
# into a manufacturer's browser.
MAX_BARCODE_LEN = 512

# GS1 Application Identifier 21 is variable length up to 20 characters. The
# character set here is narrower than GS1's own set 82: manufacturers control
# what they print, so the conservative set costs nothing and keeps quoting
# characters out of the reporting exports. Widen it if a real serial is
# rejected.
SERIAL_PATTERN = r"^[A-Za-z0-9\-_./]{1,20}$"

# 8 for EAN-8 through 14 for ITF-14. Everything normalises to 14 downstream.
GTIN_PATTERN = r"^\d{8,14}$"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ScanLookupRequest(BaseModel):
    # An unexpected key is a client bug or someone probing, and silently
    # dropping it hides both.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    barcode: str = Field(min_length=1, max_length=MAX_BARCODE_LEN)
    gtin: str = Field(min_length=8, max_length=14, pattern=GTIN_PATTERN)

    # Optional: bottles carrying only a retail EAN-13 have no serial until
    # the manufacturer starts printing GS1 DataMatrix.
    serial: Optional[str] = Field(default=None, max_length=20, pattern=SERIAL_PATTERN)

    lat: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    lng: Optional[float] = Field(default=None, ge=-180.0, le=180.0)

    @field_validator("serial", mode="before")
    @classmethod
    def empty_serial_is_none(cls, value):
        # An unserialised bottle and an empty string mean the same thing, and
        # only one of them should ever reach the ledger.
        if isinstance(value, str) and not value.strip():
            return None
        return value


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
    Registry -> serial ledger -> reuse. Each check's raw answer is stored
    alongside the verdict so the reason behind a flag stays readable later.
    """
    # Normalise once. Lookup, ledger and reporting all use the 14-digit form
    # so the parser and the catalogue can never disagree.
    gtin14 = to_gtin14(gtin)

    registry_result, product, raw_response = lookup_product(db, gtin)

    serial_result = SERIAL_UNKNOWN
    auth_reason = None
    first_scan_at = prior_scan_at = prior_scan_user_id = None
    manufacturer = None

    if registry_result != REGISTRY_REGISTERED:
        if registry_result == REGISTRY_UNREACHABLE:
            # We could not check. Say so, never imply a pass.
            auth_status = STATUS_UNKNOWN
            auth_reason = "registry unavailable"
        else:
            auth_status = STATUS_SUSPICIOUS
            auth_reason = "barcode not registered to any manufacturer"
    else:
        manufacturer = db.get(Manufacturer, product.manufacturer_id)

        serial_result, serial_reason = verify_serial(db, product, serial)

        if serial_result == SERIAL_NOT_ISSUED:
            auth_status = STATUS_SUSPICIOUS
            auth_reason = serial_reason

        elif serial_result == SERIAL_UNKNOWN:
            # Known product, nothing verifiable about this bottle.
            auth_status = STATUS_UNKNOWN
            auth_reason = serial_reason

        else:
            # A genuine serial can still have been cloned onto a fake.
            (
                auth_status,
                auth_reason,
                first_scan_at,
                prior_scan_at,
                prior_scan_user_id,
            ) = check_reuse(db, gtin14, serial, current_user_id)

    # Resolved here rather than at read time, for the same reason as brand
    # and category: reporting should never do geometry, and the scan records
    # where it happened even if boundaries are redrawn later.
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
        location_lat=lat,
        location_lng=lng,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    # The product details are only established fact when the whole chain
    # passed. A fabricated serial usually means the barcode was copied too,
    # so naming the product there would assert something we do not know.
    # Anything else is what the label CLAIMS to be.
    product_verified = auth_status == STATUS_VERIFIED

    return {
        "scan_event_id": event.id,
        "auth_status": auth_status,
        "auth_reason": auth_reason,
        "product": (
            {
                "brand": product.brand,
                "name": product.product_name,
                "manufacturer": manufacturer.name if manufacturer else None,
            }
            if product
            else None
        ),
        "product_verified": product_verified,
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

    Kept only for APK builds already in the field. Remove once those are gone.
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