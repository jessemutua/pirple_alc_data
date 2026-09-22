# scripts/cleanup_test_users.py
"""
Find test accounts and delete them, with everything they created.

    python scripts/cleanup_test_users.py                          # list only
    python scripts/cleanup_test_users.py --like "jesse+%@gmail.com"
    python scripts/cleanup_test_users.py --email tester@mail.com --apply

Accounts are matched by email: SQL LIKE patterns (--like, repeatable, case
insensitive) and exact addresses (--email, repeatable). With neither, it
matches the throwaway accounts scripts/test_scan.py creates, which all end
in @example.com.

Nothing changes without --apply, and --apply asks you to type the number of
accounts first. It runs as one transaction: all of it happens or none of it.

For each account it removes the drinks logged, the sessions they sit in,
sober days, scans and reports. Any seal a test account marked as opened
goes back to unopened, so the seeded ledger stays usable. Where a real
person's scan recorded a test account as the previous scanner, that
reference is cleared.

Before deleting, it checks every table with a user_id column. If one it
doesn't know about holds rows for these accounts, it stops and names it,
rather than leave data behind that points at nobody.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from core.database import engine  # noqa: E402

DEFAULT_PATTERNS = ["%@example.com"]

# Tables this script clears itself, in the order it clears them.
HANDLED_TABLES = {"bottle_reports", "drink_sessions", "sober_days", "scan_events"}


def describe_target() -> str:
    """Host and database name only, never the password."""
    url = make_url(str(engine.url))
    return f"{url.host or 'localhost'}/{url.database}"


def find_accounts(conn, patterns: list[str], emails: list[str]) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT u.id, u.email, u.created_at,
                   (SELECT count(*) FROM drink_sessions s WHERE s.user_id = u.id) AS sessions,
                   (SELECT count(*) FROM scan_events e WHERE e.user_id = u.id)   AS scans,
                   (SELECT count(*) FROM bottle_reports r WHERE r.user_id = u.id) AS reports,
                   (SELECT count(*) FROM product_serials p WHERE p.retired_by = u.id) AS opened
            FROM users u
            WHERE u.email ILIKE ANY(:patterns)
               OR lower(u.email) = ANY(:emails)
            ORDER BY u.created_at
            """
        ),
        {"patterns": patterns, "emails": [e.lower() for e in emails]},
    ).mappings().all()
    return [dict(r) for r in rows]


def unknown_references(conn, ids: list[str]) -> list[tuple[str, int]]:
    """Tables with a user_id column, not handled here, that hold these accounts' rows."""
    tables = conn.execute(
        text(
            """
            SELECT table_name FROM information_schema.columns
            WHERE table_schema = 'public' AND column_name = 'user_id'
            """
        )
    ).scalars().all()

    found = []
    for table in sorted(set(tables) - HANDLED_TABLES):
        count = conn.execute(
            text(f'SELECT count(*) FROM "{table}" WHERE user_id = ANY(:ids)'),
            {"ids": ids},
        ).scalar()
        if count:
            found.append((table, count))
    return found


def delete_accounts(conn, ids: list[str]) -> dict:
    p = {"ids": ids}
    done = {}

    done["seals reopened"] = conn.execute(
        text(
            """
            UPDATE product_serials
            SET retired_at = NULL, retired_by = NULL, retired_lat = NULL, retired_lng = NULL
            WHERE retired_by = ANY(:ids)
            """
        ),
        p,
    ).rowcount

    done["reports"] = conn.execute(
        text("DELETE FROM bottle_reports WHERE user_id = ANY(:ids)"), p
    ).rowcount

    # Drinks go with their session (ON DELETE CASCADE), but deleting them
    # first keeps the count honest and doesn't depend on the cascade.
    done["drinks"] = conn.execute(
        text(
            """
            DELETE FROM drink_session_items
            WHERE session_id IN (SELECT id FROM drink_sessions WHERE user_id = ANY(:ids))
            """
        ),
        p,
    ).rowcount

    done["sessions"] = conn.execute(
        text("DELETE FROM drink_sessions WHERE user_id = ANY(:ids)"), p
    ).rowcount

    done["sober days"] = conn.execute(
        text("DELETE FROM sober_days WHERE user_id = ANY(:ids)"), p
    ).rowcount

    done["references cleared"] = conn.execute(
        text(
            """
            UPDATE scan_events SET prior_scan_user_id = NULL
            WHERE prior_scan_user_id = ANY(:ids) AND NOT (user_id = ANY(:ids))
            """
        ),
        p,
    ).rowcount

    done["scans"] = conn.execute(
        text("DELETE FROM scan_events WHERE user_id = ANY(:ids)"), p
    ).rowcount

    done["accounts"] = conn.execute(
        text("DELETE FROM users WHERE id = ANY(:ids)"), p
    ).rowcount

    return done


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete test accounts and their data.")
    parser.add_argument("--like", action="append", default=[], help="email LIKE pattern")
    parser.add_argument("--email", action="append", default=[], help="exact email")
    parser.add_argument("--apply", action="store_true", help="actually delete")
    args = parser.parse_args()

    patterns = args.like or ([] if args.email else DEFAULT_PATTERNS)
    print(f"target : {describe_target()}")
    print(f"match  : {', '.join(patterns + args.email)}\n")

    with engine.begin() as conn:
        accounts = find_accounts(conn, patterns, args.email)
        if not accounts:
            print("no matching accounts")
            return 0

        print(f"{'email':44} {'created':10} {'sessions':>8} {'scans':>6} {'reports':>7} {'opened':>6}")
        for a in accounts:
            created = a["created_at"].date().isoformat() if a["created_at"] else "-"
            print(
                f"{a['email'][:44]:44} {created:10} {a['sessions']:>8} "
                f"{a['scans']:>6} {a['reports']:>7} {a['opened']:>6}"
            )
        print(f"\n{len(accounts)} account(s)")

        ids = [a["id"] for a in accounts]
        unknown = unknown_references(conn, ids)
        if unknown:
            print("\nstopping: these tables also hold rows for these accounts")
            for table, count in unknown:
                print(f"  {table}: {count}")
            print("nothing was deleted")
            return 1

        if not args.apply:
            print("\nnothing deleted. Re-run with --apply to delete these.")
            return 0

        answer = input(f"\nType {len(accounts)} to delete these accounts and their data: ")
        if answer.strip() != str(len(accounts)):
            print("cancelled, nothing deleted")
            return 1

        done = delete_accounts(conn, ids)

    print("\ndeleted")
    for label, count in done.items():
        print(f"  {label:20} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())