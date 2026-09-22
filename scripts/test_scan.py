# scripts/test_scan.py
"""
End-to-end test of the scan verdicts, against the rules in
verification/engine.py.

Requires the API running:  uvicorn main:app --reload

    python scripts/test_scan.py
    API_BASE=https://your-service.onrender.com python scripts/test_scan.py

It picks never-scanned seals straight from the database, so DATABASE_URL in
your .env must point at the same database as the API you are testing.

It writes real rows there: two throwaway accounts, a handful of scan
events, and one seeded seal that it marks as opened (retired). Point it at
a local database if you would rather production stayed untouched.

No settings to change first. The engine judges a clone by distance, not by
waiting, so the clone case just scans from far enough away.
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

# Where each scan happens. The engine treats two fixes more than 500 m apart
# as different places, and anything within 300 m as the same table.
NAIROBI_CBD = (-1.2921, 36.8219)
SAME_TABLE = (-1.2925, 36.8221)   # about 50 m from the CBD point
WESTLANDS = (-1.2676, 36.8108)    # about 3 km from the CBD point
MOMBASA = (-4.0435, 39.6682)      # about 440 km away


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
        print(f"\nCannot reach {API_BASE}. Is the server running?\n{exc.reason}")
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


def fresh_seals(count: int) -> list[tuple[str, str]]:
    """
    Issued, unopened seals on active products that nobody has ever scanned.

    Seeded scan data backdates months of activity, so a seal with history
    could legitimately come back flagged. Each case needs its own clean one.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            select(ProductSerial.gtin14, ProductSerial.serial)
            .join(Product, Product.gtin14 == ProductSerial.gtin14)
            .where(
                Product.is_active.is_(True),
                ProductSerial.status == "issued",
                ProductSerial.retired_at.is_(None),
                ~exists().where(
                    ScanEvent.serial == ProductSerial.serial,
                    ScanEvent.gtin == ProductSerial.gtin14,
                ),
            )
            .limit(count)
        ).all()
    finally:
        db.close()

    if len(rows) < count:
        print(
            f"need {count} unscanned seals, found {len(rows)}. Reseed with:\n"
            "  python scripts/seed_products.py --serials 400"
        )
        raise SystemExit(1)
    return [(row[0], row[1]) for row in rows]


def scan(token: str, gtin: str, serial: str = None, where=NAIROBI_CBD, barcode: str = None) -> dict:
    lat, lng = where
    return call(
        "/products/lookup",
        {
            "barcode": barcode or f"01{gtin}21{serial or ''}",
            "gtin": gtin,
            "serial": serial,
            "lat": lat,
            "lng": lng,
        },
        token,
    )


def retire(token: str, gtin: str, serial: str, where=NAIROBI_CBD) -> dict:
    lat, lng = where
    return call(
        "/products/retire",
        {"gtin": gtin, "serial": serial, "lat": lat, "lng": lng},
        token,
    )


def report(label: str, expected: str, result: dict) -> bool:
    if "_http_error" in result:
        print(f"  FAIL  {label:34} HTTP {result['_http_error']}  {result['_body']}")
        return False

    # "status" is the current field. "auth_status" is the old name, kept by
    # the API until every app has updated.
    got = str(result.get("status") or result.get("auth_status"))
    ok = got == expected
    reason = result.get("auth_reason") or "-"

    print(f"  {'PASS' if ok else 'FAIL':5} {label:34} {got:11} {reason}")
    return ok


def main() -> int:
    (g1, s1), (g2, s2), (g3, s3) = fresh_seals(3)
    print(f"api     : {API_BASE}")
    print(f"seals   : {g1}/{s1}, {g2}/{s2}, {g3}/{s3}\n")

    user_a = new_account()
    user_b = new_account()

    results = []

    # 1. An issued seal nobody has scanned.
    results.append(report("valid seal", "verified", scan(user_a, g1, s1)))

    # 2. The same person again, 3 km away. Shop, then home: never a clone.
    results.append(
        report("same person, 3 km away", "verified", scan(user_a, g1, s1, WESTLANDS))
    )

    # 3. Somebody else, 440 km away. One code on two bottles.
    results.append(
        report("other person, 440 km away", "suspicious", scan(user_b, g1, s1, MOMBASA))
    )

    # 4. Two people at one table, on a fresh seal. A shared bottle, not a clone.
    scan(user_a, g2, s2, NAIROBI_CBD)
    results.append(
        report("other person, same table", "verified", scan(user_b, g2, s2, SAME_TABLE))
    )

    # 5. Opened, then scanned again. The seal in hand cannot be the original.
    scan(user_a, g3, s3)
    retired = retire(user_a, g3, s3)
    if not retired.get("retired"):
        print(f"  FAIL  {'retire the seal':34} {retired}")
        results.append(False)
    else:
        results.append(
            report("scanned after opening", "suspicious", scan(user_a, g3, s3))
        )

    # 6. A real product with a seal code the manufacturer never issued.
    results.append(
        report("seal never issued", "suspicious", scan(user_a, g1, "FAKE000001"))
    )

    # 7. A plain retail barcode: the product is known, the bottle is not.
    results.append(
        report("no seal code (plain EAN)", "unknown", scan(user_a, g1, None, barcode=g1))
    )

    # 8. A brand not on Limi. Nothing to check against, so no verdict.
    results.append(
        report("brand not on Limi", "unknown", scan(user_a, "09999999999993", "XYZ123"))
    )

    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())