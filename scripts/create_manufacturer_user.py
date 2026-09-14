# scripts/create_manufacturer_user.py
"""
Create or update a manufacturer dashboard login.

    python scripts/create_manufacturer_user.py --manufacturer kwal --email ops@kwal.co.ke
    python scripts/create_manufacturer_user.py --manufacturer kwal --email ops@kwal.co.ke \
        --name "Jane Njeri" --role admin

Omit --password and a strong one is generated and printed once. Passing a
password on the command line puts it in your shell history — avoid it except
for throwaway test accounts.

Re-running with an existing email resets that account's password and role.
"""
import argparse
import secrets
import string
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from core.security import hash_password  # noqa: E402
from products.models import Manufacturer  # noqa: E402
from reporting.models import MANUFACTURER_ROLES, ManufacturerUser  # noqa: E402

PASSWORD_LENGTH = 20


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    return "".join(secrets.choice(alphabet) for _ in range(PASSWORD_LENGTH))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a manufacturer dashboard login.")
    parser.add_argument("--manufacturer", required=True, help="manufacturer slug, e.g. kwal")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default=None, help="omit to generate one")
    parser.add_argument("--name", default=None)
    parser.add_argument("--role", default="viewer", choices=list(MANUFACTURER_ROLES))
    args = parser.parse_args()

    email = args.email.strip().lower()
    password = args.password or generate_password()
    generated = args.password is None

    db = SessionLocal()
    try:
        manufacturer = db.scalar(
            select(Manufacturer).where(Manufacturer.slug == args.manufacturer)
        )
        if manufacturer is None:
            known = db.scalars(select(Manufacturer.slug).order_by(Manufacturer.slug)).all()
            print(f"unknown manufacturer: {args.manufacturer}")
            print(f"known slugs: {', '.join(known) or '(none — run seed_products.py)'}")
            return 2

        user = db.scalar(select(ManufacturerUser).where(ManufacturerUser.email == email))

        if user is None:
            user = ManufacturerUser(
                manufacturer_id=manufacturer.id,
                email=email,
                password_hash=hash_password(password),
                full_name=args.name,
                role=args.role,
                is_active=True,
            )
            db.add(user)
            action = "created"
        else:
            user.manufacturer_id = manufacturer.id
            user.password_hash = hash_password(password)
            user.role = args.role
            user.is_active = True
            if args.name:
                user.full_name = args.name
            action = "updated"

        db.commit()
        db.refresh(user)

        print(f"{action}      : {user.email}")
        print(f"manufacturer : {manufacturer.name} ({manufacturer.slug})")
        print(f"role         : {user.role}")
        print(f"live         : {manufacturer.is_live}")

        if generated:
            print(f"\npassword     : {password}")
            print("This is shown once. Store it now.")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())