# scripts/seed_scans.py
"""
Generate plausible scan history for dashboard development.

    python scripts/seed_scans.py                      # 90 days, 5000 scans
    python scripts/seed_scans.py --days 30 --scans 800
    python scripts/seed_scans.py --reset              # remove generated scans

Every generated scan is internally consistent: verified scans carry serials
that really exist in the ledger, and registry_result / serial_result /
auth_reason match the verdict the live endpoint would have produced.

Times are chosen in local wall clock hours and stored in UTC, so the hour of
day curve looks like people drinking in the evening rather than shifted by
the UTC offset.

Generated rows use a 'seed:' user_id prefix so --reset can remove exactly
what this script created, leaving real scans untouched.
"""
import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from drinks.scan_models import ScanEvent, uuid_str  # noqa: E402
from products.models import Product, ProductSerial  # noqa: E402
from reporting.service import REPORT_ZONE  # noqa: E402

SEED_USER_PREFIX = "seed:"

# Nairobi sampling points. weight = share of scan volume,
# counterfeit = share of that area's scans that come back suspicious.
AREAS = [
    {"name": "Westlands",  "lat": -1.2649, "lng": 36.8035, "weight": 14, "counterfeit": 0.08},
    {"name": "CBD",        "lat": -1.2841, "lng": 36.8233, "weight": 16, "counterfeit": 0.12},
    {"name": "Kilimani",   "lat": -1.2906, "lng": 36.7833, "weight": 11, "counterfeit": 0.06},
    {"name": "Karen",      "lat": -1.3190, "lng": 36.7060, "weight": 7,  "counterfeit": 0.03},
    {"name": "Ngong Road", "lat": -1.3000, "lng": 36.7700, "weight": 9,  "counterfeit": 0.09},
    {"name": "Eastleigh",  "lat": -1.2730, "lng": 36.8500, "weight": 10, "counterfeit": 0.34},  # hotspot
    {"name": "Githurai",   "lat": -1.1900, "lng": 36.9200, "weight": 9,  "counterfeit": 0.41},  # hotspot
    {"name": "Embakasi",   "lat": -1.3200, "lng": 36.8900, "weight": 10, "counterfeit": 0.29},  # hotspot
    {"name": "Kasarani",   "lat": -1.2200, "lng": 36.8960, "weight": 8,  "counterfeit": 0.14},
    {"name": "Rongai",     "lat": -1.3960, "lng": 36.7460, "weight": 6,  "counterfeit": 0.11},
]

# Counterfeiters target high-margin spirits far more than beer.
from drinks.drink_types import DRINK_TYPES  # noqa: E402

# Counterfeiters target high-margin spirits far more than beer. Every spirit
# type shares one weight, and cider sits with the ready-to-drinks.
SPIRIT_RISK = 1.9
CATEGORY_RISK = {
    "whisky": SPIRIT_RISK,
    "vodka": SPIRIT_RISK,
    "gin": SPIRIT_RISK,
    "brandy": SPIRIT_RISK,
    "rum": SPIRIT_RISK,
    "liqueur": SPIRIT_RISK,
    "spirits": SPIRIT_RISK,  # legacy type, kept for older rows
    "wine": 1.2,
    "rtd": 0.8,
    "cider": 0.8,
    "beer": 0.45,
    "other": 1.0,
}

# A drink type with no weight would silently fall back to 1.0.
_unweighted = set(DRINK_TYPES) - set(CATEGORY_RISK)
if _unweighted:
    raise SystemExit(f"CATEGORY_RISK has no weight for: {', '.join(sorted(_unweighted))}")
# Share of scans from bottles with no serial printed yet, a plain EAN-13.
# These are honestly unverifiable and must never read as verified.
NO_SERIAL_RATE = 0.16

# Local hours. Buying and drinking peak in the evening, quiet before noon.
HOUR_WEIGHTS = [
    3, 2, 1, 1, 1, 1, 2, 3, 4, 4, 5, 6,
    8, 8, 7, 8, 10, 14, 18, 20, 17, 12, 8, 5,
]

USER_POOL_SIZE = 240
JITTER_DEGREES = 0.012  # roughly 1.3 km


def load_catalogue(db):
    products = db.scalars(select(Product).where(Product.is_active.is_(True))).all()
    if not products:
        print("no products, run scripts/seed_products.py first")
        raise SystemExit(1)

    serials: dict[str, list[str]] = {}
    for gtin, serial in db.execute(
        select(ProductSerial.gtin14, ProductSerial.serial).where(
            ProductSerial.status == "issued"
        )
    ).all():
        serials.setdefault(gtin, []).append(serial)

    return products, serials


def weighted_choice(items, key):
    total = sum(key(i) for i in items)
    threshold = random.uniform(0, total)
    running = 0.0
    for item in items:
        running += key(item)
        if running >= threshold:
            return item
    return items[-1]


def random_timestamp(days: int) -> datetime:
    """
    A local wall clock moment, returned in UTC.

    The hour is chosen against local time, so reporting groups it into the
    evening where it belongs rather than three hours later.
    """
    now_local = datetime.now(REPORT_ZONE)
    day_offset = random.randint(0, max(days - 1, 0))
    when = now_local - timedelta(days=day_offset)

    # Weekend uplift, on the local weekday.
    if when.weekday() < 5 and random.random() < 0.33:
        when -= timedelta(days=random.randint(1, 3))

    hour = random.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]

    local = when.replace(
        hour=hour,
        minute=random.randint(0, 59),
        second=random.randint(0, 59),
        microsecond=0,
    )

    return local.astimezone(timezone.utc)


def fabricated_serial() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(10))


def build_scan(product, serials, users, days) -> ScanEvent:
    area = weighted_choice(AREAS, key=lambda a: a["weight"])
    created = random_timestamp(days)
    user_id = random.choice(users)

    gtin = product.gtin14
    issued = serials.get(gtin, [])

    # Does this bottle carry a serial at all?
    has_serial = bool(issued) and random.random() > NO_SERIAL_RATE

    if not has_serial:
        serial = None
        registry_result = "registered"
        serial_result = "unknown"
        status = "unknown"
        reason = "no serial in barcode"
        first_scan_at = prior_scan_at = prior_user = None
    else:
        risk = area["counterfeit"] * CATEGORY_RISK.get(product.category, 1.0)
        is_counterfeit = random.random() < min(risk, 0.85)

        registry_result = "registered"

        if not is_counterfeit:
            serial = random.choice(issued)
            serial_result = "issued"
            status = "verified"
            reason = None
            first_scan_at = created
            prior_scan_at = prior_user = None

        elif random.random() < 0.6:
            # Fabricated serial: a copied label with an invented number.
            serial = fabricated_serial()
            serial_result = "not_issued"
            status = "suspicious"
            reason = "serial not issued by manufacturer"
            first_scan_at = created
            prior_scan_at = prior_user = None

        else:
            # Cloned serial: a real number duplicated onto a fake.
            serial = random.choice(issued)
            serial_result = "issued"
            status = "suspicious"
            hours = random.randint(26, 900)
            reason = f"originally scanned by another user {hours}h ago"
            prior_scan_at = created - timedelta(hours=hours)
            first_scan_at = prior_scan_at
            prior_user = random.choice(users)

    lat = area["lat"] + random.uniform(-JITTER_DEGREES, JITTER_DEGREES)
    lng = area["lng"] + random.uniform(-JITTER_DEGREES, JITTER_DEGREES)

    return ScanEvent(
        id=uuid_str(),
        user_id=user_id,
        barcode_raw=f"01{gtin}" + (f"21{serial}" if serial else ""),
        gtin=gtin,
        serial=serial,
        registry_result=registry_result,
        serial_result=serial_result,
        manufacturer_raw_response=None,
        manufacturer_id=product.manufacturer_id,
        brand=product.brand,
        category=product.category,
        first_scan_at=first_scan_at,
        prior_scan_at=prior_scan_at,
        prior_scan_user_id=prior_user,
        combined_auth_status=status,
        auth_reason=reason,
        location_lat=round(lat, 6),
        location_lng=round(lng, 6),
        created_at=created,
    )


def reset_generated(db) -> None:
    removed = (
        db.query(ScanEvent)
        .filter(ScanEvent.user_id.like(f"{SEED_USER_PREFIX}%"))
        .delete(synchronize_session=False)
    )
    db.commit()
    print(f"reset  : removed {removed} generated scans")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate scan history for dashboard work.")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--scans", type=int, default=5000)
    parser.add_argument("--reset", action="store_true", help="remove generated scans first")
    parser.add_argument("--seed", type=int, default=None, help="rng seed, for reproducible data")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    db = SessionLocal()
    try:
        if args.reset:
            reset_generated(db)
            if args.scans == 0:
                return 0

        products, serials = load_catalogue(db)
        users = [f"{SEED_USER_PREFIX}{uuid.uuid4()}" for _ in range(USER_POOL_SIZE)]

        print(f"products: {len(products)}  users: {len(users)}  days: {args.days}")

        batch = []
        counts = {"verified": 0, "suspicious": 0, "unknown": 0}

        for index in range(args.scans):
            product = random.choice(products)
            event = build_scan(product, serials, users, args.days)
            counts[event.combined_auth_status] += 1
            batch.append(event)

            if len(batch) >= 1000:
                db.bulk_save_objects(batch)
                db.commit()
                print(f"  written {index + 1}/{args.scans}")
                batch = []

        if batch:
            db.bulk_save_objects(batch)
            db.commit()

        total = sum(counts.values())
        print(f"\nscans  : {total}")
        for status, n in counts.items():
            print(f"  {status:11} {n:6}  {n / total:.1%}")
    finally:
        db.close()

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())