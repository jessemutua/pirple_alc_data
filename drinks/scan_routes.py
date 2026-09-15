# drinks/scan_routes.py
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ScanLookupRequest(BaseModel):
    barcode: str
    gtin: str
    # Optional: bottles carrying only a retail EAN-13 have no serial until
    # the manufacturer starts printing GS1 DataMatrix.
    serial: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


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
    barcode: str = Query(...),
    gtin: str = Query(...),
    serial: str = Query(None),
    lat: float = Query(None),
    lng: float = Query(None),
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