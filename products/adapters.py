# products/adapters.py
"""
Product registry — the single interface between scanning and the catalogue.

Callers never query products or serials directly. That keeps the source of
truth swappable: seeded data today, a manufacturer's own system tomorrow,
decided per-manufacturer by Manufacturer.verification_mode.
"""
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from products.models import Manufacturer, Product, ProductSerial

# Was the barcode itself recognised?
REGISTRY_REGISTERED = "registered"
REGISTRY_NOT_FOUND = "not_found"
REGISTRY_UNREACHABLE = "unreachable"

# Was this individual serial ever issued?
SERIAL_ISSUED = "issued"
SERIAL_NOT_ISSUED = "not_issued"
SERIAL_UNKNOWN = "unknown"


def to_gtin14(raw: Optional[str]) -> Optional[str]:
    """
    Normalise any barcode form to 14 zero-padded digits.

    GS1 AI (01) is always 14, while retail EAN-13 and UPC-12 are shorter.
    Everything is stored and compared at 14 so the two can never disagree.
    Returns None if the input isn't a usable numeric barcode.
    """
    if not raw:
        return None

    digits = "".join(c for c in str(raw) if c.isdigit())
    if not digits or len(digits) > 14:
        return None

    return digits.zfill(14)


def lookup_product(
    db: Session, gtin_raw: str
) -> Tuple[str, Optional[Product], Optional[dict]]:
    """
    Resolve a barcode to a product.

    Returns (registry_result, product, raw_response). raw_response is stored
    on the scan event for audit — it stands in for what a manufacturer's API
    would have returned.
    """
    gtin14 = to_gtin14(gtin_raw)
    if gtin14 is None:
        return REGISTRY_NOT_FOUND, None, {"gtin_raw": gtin_raw, "error": "unparseable"}

    try:
        product = db.scalar(
            select(Product).where(
                Product.gtin14 == gtin14,
                Product.is_active.is_(True),
            )
        )
    except Exception:
        # Registry could not be consulted. Deliberately distinct from
        # "not found" — we don't know, and must not imply otherwise.
        return REGISTRY_UNREACHABLE, None, None

    if product is None:
        return REGISTRY_NOT_FOUND, None, {"gtin": gtin14, "found": False}

    return (
        REGISTRY_REGISTERED,
        product,
        {
            "gtin": gtin14,
            "found": True,
            "brand": product.brand,
            "name": product.product_name,
            "category": product.category,
        },
    )


def verify_serial(
    db: Session, product: Product, serial: Optional[str]
) -> Tuple[str, Optional[str]]:
    """
    Was this serial issued for this product?

    Scoped to the product because GS1 only guarantees serial uniqueness
    within a GTIN — two manufacturers may legitimately issue the same string.

    Returns (serial_result, reason).
    """
    if not serial:
        return SERIAL_UNKNOWN, "no serial in barcode"

    manufacturer = db.get(Manufacturer, product.manufacturer_id)
    mode = manufacturer.verification_mode if manufacturer else "ledger"

    if mode == "api":
        # Live call into the manufacturer's system. Not built yet — return
        # unknown rather than a pass, so an unavailable check never reads
        # as a successful one.
        return SERIAL_UNKNOWN, "manufacturer api not configured"

    try:
        row = db.get(ProductSerial, (product.gtin14, serial))
    except Exception:
        return SERIAL_UNKNOWN, "serial ledger unavailable"

    if row is None:
        return SERIAL_NOT_ISSUED, "serial not issued by manufacturer"

    if row.status == "recalled":
        return SERIAL_NOT_ISSUED, "serial belongs to a recalled batch"

    return SERIAL_ISSUED, None


def product_payload(product: Product) -> dict:
    """Product shape returned to the mobile client. Matches ProductInfo in productApi.ts."""
    return {
        "brand": product.brand,
        "name": product.product_name,
        "manufacturer": product.manufacturer_id,
    }