# drinks/scan_models.py
import uuid

from sqlalchemy import Column, String, DateTime, Float, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from core.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


REGISTRY_RESULTS = ("registered", "not_found", "unreachable")
SERIAL_RESULTS = ("issued", "not_issued", "unknown")

# Only three, and each is a thing we can defend. "verified" means a valid
# manufacturer-issued seal, not a claim about the liquid. Nothing in
# between: telling somebody their real bottle is fake is the error that
# costs a manufacturer trust, and we have no data yet with which to justify
# taking that risk.
AUTH_STATUSES = ("unknown", "verified", "suspicious")


class ScanEvent(Base):
    __tablename__ = "scan_events"

    id = Column(String, primary_key=True, default=uuid_str)
    user_id = Column(String, nullable=False)

    barcode_raw = Column(String, nullable=False)
    gtin = Column(String, nullable=True)
    serial = Column(String, nullable=True)

    registry_result = Column(String, nullable=False, default="unreachable")
    manufacturer_raw_response = Column(JSONB, nullable=True)

    # Was this serial one the manufacturer actually issued?
    # Kept separate from registry_result and combined_auth_status so the
    # reason behind a verdict is still readable months later.
    serial_result = Column(String, nullable=True)

    # Product context, denormalised at scan time. Reporting never joins to
    # the catalogue, and a scan records what was true WHEN it happened:
    # later deactivation or reassignment cannot rewrite history.
    manufacturer_id = Column(String, nullable=True)
    brand = Column(String, nullable=True)
    category = Column(String, nullable=True)

    # Resolved from the coordinates at scan time. Null is normal: no
    # coordinates, no boundary file, or a point outside every boundary.
    county = Column(String, nullable=True)

    # Snapshot of this code's history at the moment of this scan.
    first_scan_at = Column(DateTime(timezone=True), nullable=True)
    prior_scan_at = Column(DateTime(timezone=True), nullable=True)
    prior_scan_user_id = Column(String, nullable=True)

    combined_auth_status = Column(String, nullable=False, default="unknown")
    auth_reason = Column(String, nullable=True)

    # What the manufacturer sees, which is not what the consumer is told.
    risk_score = Column(Float, nullable=False, default=0.0)
    risk_reasons = Column(JSONB, nullable=True)

    # Everything the next version of the algorithm will need, recorded on
    # every scan whether or not anything reads it today. Without this there
    # is no way to measure real baselines later, and every threshold stays
    # a guess.
    scan_features = Column(JSONB, nullable=True)

    location_lat = Column(Float, nullable=True)
    location_lng = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_scan_events_user_id", "user_id"),
        Index("ix_scan_events_serial", "serial"),
        Index("ix_scan_events_gtin", "gtin"),
        Index("ix_scan_events_manufacturer_id", "manufacturer_id"),
        Index("ix_scan_events_created_at", "created_at"),
        Index("ix_scan_events_county", "county"),
        Index(
            "ix_scan_events_risk_score",
            text("risk_score DESC"),
            text("created_at DESC"),
        ),
    )