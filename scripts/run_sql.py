# scripts/run_sql.py
"""
Run a .sql file against the database this app is configured for.

    python scripts/run_sql.py scripts/migrate_001_manufacturer_layer.sql

The whole file is sent as one transaction — Postgres DDL is transactional,
so it either fully applies or fully rolls back.
"""
import sys
from pathlib import Path

# Python puts this script's folder on sys.path, not the repo root, so the
# app packages (core, products, ...) aren't importable without this.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy.engine import make_url  # noqa: E402

from core.database import engine  # noqa: E402


def describe_target() -> str:
    """Host and database name only — never the password."""
    url = make_url(str(engine.url))
    return f"{url.host or 'localhost'}/{url.database}"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/run_sql.py <path-to-sql-file>")
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"not found: {path}")
        return 2

    sql = path.read_text().strip()
    if not sql:
        print(f"empty file: {path}")
        return 2

    print(f"target : {describe_target()}")
    print(f"script : {path}")

    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)
    except Exception as exc:
        print(f"FAILED — nothing was applied\n{type(exc).__name__}: {exc}")
        return 1

    print("applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())