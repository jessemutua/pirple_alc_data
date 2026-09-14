# scripts/test_scan.py
"""
End-to-end test of the scan verdict logic.

Requires the API running:  uvicorn main:app --reload

    python scripts/test_scan.py
    API_BASE=https://your-service.onrender.com python scripts/test_scan.py

The clone case only fires when a DIFFERENT user scanned the same serial at
least SCAN_REUSE_OTHER_USER_MIN_GAP_HOURS ago. To exercise it without
waiting, start the server with that set to 0:

    SCAN_REUSE_OTHER_USER_MIN_GAP_HOURS=0 uvicorn main:app --reload
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import exists, select  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from drinks.scan_models import ScanEvent  # noqa: E402
from products.models import Product, ProductSerial  # noqa: E402

API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")
PASSWORD = "testpass1234"


def call(path: str, payload: dict, token: str = None) -> dict:
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return {"_http_error": exc.code, "_body": exc.read().decode()[:300]}
    except urllib.error.URLError as exc:
        print(f"\nCannot reach {API_BASE} — is the server running?\n{exc.reason}")
        raise SystemExit(1)


def new_account() -> str:
    """Register a throwaway user and return its token."""
    email = f"scantest+{uuid.uuid4().hex[:10]}@example.com"
    result = call("/auth/register", {"email": email, "password": PASSWORD})

    token = result.get("access_token")
    if not token:
        print(f"could not create test account: {result}")
        raise SystemExit(1)
    return token


def genuine_pair() -> tuple[str, str]:
    """
    A real GTIN and issued serial with NO scan history.

    Seeded scan data backdates months of activity, so any serial that has
    already been scanned will legitimately trip the reuse rules. The genuine
    case needs a bottle nobody has ever scanned.
    """
    db = SessionLocal()
    try:
        row = db.execute(
            select(ProductSerial.gtin14, ProductSerial.serial)
            .join(Product, Product.gtin14 == ProductSerial.gtin14)
            .where(
                ProductSerial.status == "issued",
                ~exists().where(
                    ScanEvent.serial == ProductSerial.serial,
                    ScanEvent.gtin == ProductSerial.gtin14,
                ),
            )
            .limit(1)
        ).first()
    finally:
        db.close()

    if row is None:
        print(
            "no unscanned serials left — reseed with:\n"
            "  python scripts/seed_products.py --serials 400"
        )
        raise SystemExit(1)
    return row[0], row[1]


def scan(token: str, gtin: str, serial: str = None, barcode: str = None) -> dict:
    return call(
        "/products/lookup",
        {
            "barcode": barcode or f"01{gtin}21{serial or ''}",
            "gtin": gtin,
            "serial": serial,
            "lat": -1.2921,
            "lng": 36.8219,
        },
        token,
    )


def report(label: str, expected: str, result: dict) -> bool:
    if "_http_error" in result:
        print(f"  FAIL  {label:28} HTTP {result['_http_error']}  {result['_body']}")
        return False

    got = result.get("auth_status")
    ok = got == expected
    reason = result.get("auth_reason") or "-"
    product = (result.get("product") or {}).get("name", "-")

    print(f"  {'PASS' if ok else 'FAIL':5} {label:28} {got:11} {reason}")
    if ok and product != "-":
        print(f"        {'':28} product: {product}")
    return ok


def main() -> int:
    gtin, serial = genuine_pair()
    print(f"api     : {API_BASE}")
    print(f"testing : {gtin} / {serial}\n")

    user_a = new_account()
    user_b = new_account()

    results = []

    # 1. Genuine product, issued serial, never scanned.
    results.append(
        report("genuine serial", "verified", scan(user_a, gtin, serial))
    )

    # 2. Same serial, different user — a cloned label.
    results.append(
        report("cloned serial (user B)", "suspicious", scan(user_b, gtin, serial))
    )

    # 3. Real product, serial the manufacturer never issued.
    results.append(
        report("fabricated serial", "suspicious", scan(user_a, gtin, "FAKE000001"))
    )

    # 4. Plain retail barcode — product known, bottle unverifiable.
    results.append(
        report("no serial (plain EAN)", "unknown", scan(user_a, gtin, None, barcode=gtin))
    )

    # 5. Barcode belonging to no registered manufacturer.
    results.append(
        report("unregistered barcode", "suspicious", scan(user_a, "09999999999993", "XYZ123"))
    )

    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")

    if not results[1]:
        print(
            "\nnote: the clone case needs a different user and a time gap.\n"
            "      restart the server with SCAN_REUSE_OTHER_USER_MIN_GAP_HOURS=0"
        )

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())