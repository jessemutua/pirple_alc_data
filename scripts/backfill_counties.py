# scripts/backfill_counties.py
"""
Tag existing scans with the county they happened in.

    python scripts/backfill_counties.py              # untagged rows only
    python scripts/backfill_counties.py --all        # retag everything
    python scripts/backfill_counties.py --dry-run

Safe to re-run. By default it only touches rows that have coordinates and no
county yet, so a partial run resumes and a repeat run is a no-op.

Use --all after replacing the boundary file, since existing tags would then
be based on the old boundaries.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func, select  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from core.geo import BOUNDARIES_PATH, county_for  # noqa: E402
from drinks.scan_models import ScanEvent  # noqa: E402

BATCH = 2000
COORD_PRECISION = 4  # ~11 m, fine enough that a cache hit is the same place


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill scan counties.")
    parser.add_argument(
        "--all", action="store_true", help="retag rows that already have a county"
    )
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    if not BOUNDARIES_PATH.is_file():
        print(f"no boundary file at {BOUNDARIES_PATH}")
        print("place a Kenya counties GeoJSON there and run this again")
        return 2

    db = SessionLocal()
    cache: dict[tuple[float, float], str | None] = {}

    try:
        conditions = [
            ScanEvent.location_lat.isnot(None),
            ScanEvent.location_lng.isnot(None),
        ]
        if not args.all:
            conditions.append(ScanEvent.county.is_(None))

        total = db.scalar(
            select(func.count()).select_from(ScanEvent).where(*conditions)
        )
        print(f"candidates : {total}")

        if not total:
            print("nothing to do")
            return 0

        tagged = 0
        missed = 0
        processed = 0

        while True:
            rows = db.scalars(
                select(ScanEvent).where(*conditions).limit(BATCH)
            ).all()
            if not rows:
                break

            for row in rows:
                key = (
                    round(row.location_lat, COORD_PRECISION),
                    round(row.location_lng, COORD_PRECISION),
                )

                # Scans cluster heavily, so most lookups are cache hits.
                if key not in cache:
                    cache[key] = county_for(row.location_lat, row.location_lng)

                county = cache[key]
                if county:
                    tagged += 1
                else:
                    missed += 1

                if not args.dry_run:
                    row.county = county

                processed += 1

            if args.dry_run:
                # Nothing was written, so the same rows would come back
                # forever. One batch is enough to judge the result.
                break

            db.commit()
            print(f"  {processed}/{total}")

            if processed >= total:
                break

        print(f"\ntagged     : {tagged}")
        print(f"outside    : {missed}")
        print(f"unique pts : {len(cache)}")

        if args.dry_run:
            print("\ndry run, nothing written")
        else:
            counties = db.execute(
                select(ScanEvent.county, func.count())
                .where(ScanEvent.county.isnot(None))
                .group_by(ScanEvent.county)
                .order_by(func.count().desc())
                .limit(10)
            ).all()

            print("\ntop counties")
            for name, count in counties:
                print(f"  {name:20} {count}")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())