# drinks/scan_routes.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.database import SessionLocal
from drinks.scan_models import ScanEvent, uuid_str
from drinks.scan_reuse import check_reuse
from products.adapters import lookup_registry
from core.security import get_current_user_id

router = APIRouter(prefix="/products", tags=["scan"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/lookup")
def lookup_product(
    barcode: str = Query(...),
    gtin: str = Query(...),
    serial: str = Query(...),
    lat: float = Query(None),
    lng: float = Query(None),
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    # 1. Registry check — is this GTIN a real, known product?
    registry_result, product_info, raw_response = lookup_registry(gtin)

    # 2. Reuse check — has this serial been seen in a way that looks suspicious?
    auth_status, auth_reason, first_scan_at, prior_scan_at, prior_scan_user_id = check_reuse(
        db, serial, current_user_id
    )

    # A registry miss overrides a "verified" reuse result — an unregistered
    # product can't be called verified no matter what the reuse check says.
    if registry_result != "registered" and auth_status == "verified":
        auth_status = "unknown" if registry_result == "unreachable" else "suspicious"
        auth_reason = auth_reason or f"registry check: {registry_result}"

    # 3. Store this scan, unconditionally — every scan is recorded.
    event = ScanEvent(
        id=uuid_str(),
        user_id=current_user_id,
        barcode_raw=barcode,
        gtin=gtin,
        serial=serial,
        registry_result=registry_result,
        manufacturer_raw_response=raw_response,
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

    # 4. Return just what the FE needs.
    return {
        "scan_event_id": event.id,
        "auth_status": auth_status,
        "auth_reason": auth_reason,
        "product": product_info,
    }