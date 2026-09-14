# products/models.py
import uuid

from sqlalchemy import (
    Column, String, Integer, Numeric, Boolean, DateTime,
    ForeignKey, ForeignKeyConstraint, Index, PrimaryKeyConstraint,
)
from sqlalchemy.sql import func

from core.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


# Provenance of a row. Swapping seeded data for real manufacturer data
# is an INSERT/DELETE on this column, not a migration.
SOURCES = ("seed", "feed", "api")

# How a manufacturer's serials get verified.
#   ledger -> issued serials held locally (seeded, or pushed by them)
#   api    -> call their system live on every scan
VERIFICATION_MODES = ("ledger", "api")

CATEGORIES = ("beer", "wine", "spirits", "rtd", "other")

SERIAL_STATUSES = ("issued", "recalled")

DEFAULT_CURRENCY = "KES"


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)

    # Stable machine key (e.g. "kwal", "eabl"). Seed scripts and
    # manufacturer logins reference this, never the random uuid.
    slug = Column(String, nullable=False, unique=True, index=True)

    # False = placeholder we created for catalogue coverage.
    # True  = onboarded partner with dashboard access.
    is_live = Column(Boolean, nullable=False, default=False)

    verification_mode = Column(String, nullable=False, default="ledger")
    api_endpoint = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Product(Base):
    __tablename__ = "products"

    # The barcode is the natural identity. Always 14 digits, zero-padded —
    # this is what keeps the GS1 parser and the catalogue in agreement.
    gtin14 = Column(String(14), primary_key=True)

    manufacturer_id = Column(
        String, ForeignKey("manufacturers.id"), nullable=False
    )

    brand = Column(String, nullable=False)
    product_name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    volume_ml = Column(Integer, nullable=True)

    # What the manufacturer sells the unit for — ex-factory or trade price.
    # This is the basis for counterfeit exposure: it's the revenue actually
    # diverted per bottle, and the figure a manufacturer already records.
    unit_price = Column(Numeric(12, 2), nullable=True)

    # Shelf price. A different number, owned by a different party — kept
    # separate so exposure is never silently inflated by retail margin.
    retail_price = Column(Numeric(12, 2), nullable=True)

    # Explicit, not assumed. Mixing currencies without saying so is worse
    # than reporting no value at all.
    currency = Column(String(3), nullable=False, default=DEFAULT_CURRENCY)

    source = Column(String, nullable=False, default="seed")

    # Soft delete. Never hard-delete a product that scans point at.
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_products_manufacturer_id", "manufacturer_id"),
        Index("ix_products_category", "category"),
    )


class ProductSerial(Base):
    __tablename__ = "product_serials"

    gtin14 = Column(String(14), nullable=False)
    serial = Column(String, nullable=False)

    batch = Column(String, nullable=True)
    status = Column(String, nullable=False, default="issued")
    source = Column(String, nullable=False, default="seed")

    # When the manufacturer minted it, not when we recorded it.
    issued_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # GS1 guarantees serial uniqueness only WITHIN a GTIN.
        PrimaryKeyConstraint("gtin14", "serial"),
        ForeignKeyConstraint(["gtin14"], ["products.gtin14"]),
        Index("ix_product_serials_gtin14", "gtin14"),
    )