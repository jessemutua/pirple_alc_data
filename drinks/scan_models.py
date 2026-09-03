# drinks/scan_models.py
import uuid

from sqlalchemy import Column, String, DateTime, Float, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from core.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


REGISTRY_RESULTS = ("registered", "not_found", "unreachable")
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

    # snapshot of this serial's scan history at the moment of this scan,
    # used by the reuse rule without needing a separate query every time
    first_scan_at = Column(DateTime(timezone=True), nullable=True)
    prior_scan_at = Column(DateTime(timezone=True), nullable=True)
    prior_scan_user_id = Column(String, nullable=True)

    combined_auth_status = Column(String, nullable=False, default="unknown")
    auth_reason = Column(String, nullable=True)

    location_lat = Column(Float, nullable=True)
    location_lng = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_scan_events_user_id", "user_id"),
        Index("ix_scan_events_serial", "serial"),
        Index("ix_scan_events_gtin", "gtin"),
    )