# scripts/seed_products.py
"""
Load the product catalogue and mint issued serials for every SKU.

    python scripts/seed_products.py                 # 200 serials per product
    python scripts/seed_products.py --serials 50
    python scripts/seed_products.py --reset         # drop seeded rows first

Idempotent: manufacturers and products are upserted by their natural keys,
and each product is topped up to exactly --serials seeded serials. Re-running
never duplicates anything.

Only rows with source='seed' are ever touched, so when a manufacturer sends
real data (source='feed'), this script leaves it alone.
"""
import argparse
import json
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func, select  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from products.models import (  # noqa: E402
    CATEGORIES,
    Manufacturer,
    Product,
    ProductSerial,
)

CATALOGUE_PATH = REPO_ROOT / "products" / "seed_catalogue.json"

# No 0/O/1/I — these get transcribed by humans when something goes wrong.
SERIAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SERIAL_LENGTH = 10
DEFAULT_SERIALS_PER_PRODUCT = 200

SEED = "seed"


def check_digit(body: str) -> str:
    """GS1 mod-10 over the 12 digits preceding the check digit."""
    total = sum(
        (3 if i % 2 == 0 else 1) * int(d)
        for i, d in enumerate(reversed(body))
    )
    return str((10 - total % 10) % 10)


def validate_catalogue(data: dict) -> None:
    """Fail loudly on a malformed catalogue rather than seeding junk."""
    slugs = {m["slug"] for m in data["manufacturers"]}
    seen_gtins = set()

    for p in data["products"]:
        gtin = p["gtin14"]

        if len(gtin) != 14 or not gtin.isdigit():
            raise ValueError(f"{gtin}: not 14 digits")
        if gtin[-1] != check_digit(gtin[1:13]):
            raise ValueError(f"{gtin}: bad GS1 check digit")
        if gtin in seen_gtins:
            raise ValueError(f"{gtin}: duplicate")
        if p["manufacturer"] not in slugs:
            raise ValueError(f"{gtin}: unknown manufacturer {p['manufacturer']!r}")
        if p["category"] not in CATEGORIES:
            raise ValueError(f"{gtin}: unknown category {p['category']!r}")

        seen_gtins.add(gtin)


def make_serial() -> str:
    return "".join(secrets.choice(SERIAL_ALPHABET) for _ in range(SERIAL_LENGTH))


def sync_manufacturers(db, rows: list[dict]) -> dict[str, str]:
    """Upsert by slug. Returns slug -> id."""
    ids: dict[str, str] = {}

    for row in rows:
        existing = db.scalar(
            select(Manufacturer).where(Manufacturer.slug == row["slug"])
        )
        if existing is None:
            existing = Manufacturer(
                name=row["name"],
                slug=row["slug"],
                is_live=row.get("is_live", False),
                verification_mode=row.get("verification_mode", "ledger"),
                api_endpoint=row.get("api_endpoint"),
            )
            db.add(existing)
            db.flush()
        else:
            existing.name = row["name"]
            existing.is_live = row.get("is_live", False)
            existing.verification_mode = row.get("verification_mode", "ledger")
            existing.api_endpoint = row.get("api_endpoint")

        ids[row["slug"]] = existing.id

    db.commit()
    return ids


def sync_products(db, rows: list[dict], manufacturer_ids: dict[str, str]) -> int:
    """Upsert by gtin14. Returns count written."""
    for row in rows:
        existing = db.get(Product, row["gtin14"])
        if existing is None:
            db.add(
                Product(
                    gtin14=row["gtin14"],
                    manufacturer_id=manufacturer_ids[row["manufacturer"]],
                    brand=row["brand"],
                    product_name=row["product_name"],
                    category=row["category"],
                    volume_ml=row.get("volume_ml"),
                    source=SEED,
                    is_active=True,
                )
            )
        else:
            existing.manufacturer_id = manufacturer_ids[row["manufacturer"]]
            existing.brand = row["brand"]
            existing.product_name = row["product_name"]
            existing.category = row["category"]
            existing.volume_ml = row.get("volume_ml")
            existing.is_active = True

    db.commit()
    return len(rows)


def top_up_serials(db, gtins: list[str], target: int) -> int:
    """Bring each product up to `target` seeded serials. Returns count minted."""
    minted = 0

    for gtin in gtins:
        have = db.scalar(
            select(func.count())
            .select_from(ProductSerial)
            .where(ProductSerial.gtin14 == gtin, ProductSerial.source == SEED)
        )
        needed = target - (have or 0)
        if needed <= 0:
            continue

        taken = set(
            db.scalars(
                select(ProductSerial.serial).where(ProductSerial.gtin14 == gtin)
            ).all()
        )

        fresh = []
        while len(fresh) < needed:
            candidate = make_serial()
            if candidate in taken:
                continue
            taken.add(candidate)
            fresh.append(candidate)

        db.bulk_save_objects(
            [
                ProductSerial(
                    gtin14=gtin,
                    serial=s,
                    batch=f"SEED-{gtin[-5:]}",
                    status="issued",
                    source=SEED,
                )
                for s in fresh
            ]
        )
        db.commit()
        minted += needed

    return minted


def reset_seeded(db) -> None:
    """Remove seeded rows only. Manufacturer-supplied data is left intact."""
    serials = db.query(ProductSerial).filter(ProductSerial.source == SEED).delete()
    products = db.query(Product).filter(Product.source == SEED).delete()
    db.commit()
    print(f"reset  : removed {serials} serials, {products} products")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the product catalogue.")
    parser.add_argument(
        "--serials",
        type=int,
        default=DEFAULT_SERIALS_PER_PRODUCT,
        help=f"issued serials per product (default {DEFAULT_SERIALS_PER_PRODUCT})",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete existing seeded products and serials first",
    )
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=CATALOGUE_PATH,
        help="path to the catalogue JSON",
    )
    args = parser.parse_args()

    if not args.catalogue.is_file():
        print(f"catalogue not found: {args.catalogue}")
        return 2

    data = json.loads(args.catalogue.read_text())

    try:
        validate_catalogue(data)
    except (KeyError, ValueError) as exc:
        print(f"catalogue invalid — nothing written\n{exc}")
        return 1

    db = SessionLocal()
    try:
        if args.reset:
            reset_seeded(db)

        ids = sync_manufacturers(db, data["manufacturers"])
        print(f"mfrs   : {len(ids)}")

        count = sync_products(db, data["products"], ids)
        print(f"skus   : {count}")

        gtins = [p["gtin14"] for p in data["products"]]
        minted = top_up_serials(db, gtins, args.serials)
        print(f"serials: {minted} minted ({args.serials} per sku)")

        total = db.scalar(select(func.count()).select_from(ProductSerial))
        print(f"ledger : {total} serials total")
    finally:
        db.close()

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())