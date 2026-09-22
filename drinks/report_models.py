# drinks/report_models.py
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import func

from core.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


# Mirrors ck_bottle_reports_reason in migrate_007_bottle_reports.sql.
REPORT_REASONS = ("taste_smell_wrong", "felt_unwell", "other")

MAX_NOTE_LEN = 280


class BottleReport(Base):
    """
    One person's account of one bottle they scanned. Never a claim about a
    brand, and never a verdict on what was in the bottle.
    """

    __tablename__ = "bottle_reports"

    id = Column(String, primary_key=True, default=uuid_str)
    user_id = Column(String, nullable=False)
    scan_event_id = Column(String, ForeignKey("scan_events.id"), nullable=False)

    reason = Column(String, nullable=False)
    note = Column(String(MAX_NOTE_LEN), nullable=True)

    # The wording of the consent line the person agreed to when sending.
    consent_version = Column(String, nullable=False)

    # Copied from the scan event at report time, so the manufacturer view
    # reads this table alone and never joins back to user-level scan rows.
    manufacturer_id = Column(String, nullable=True)
    gtin = Column(String(14), nullable=True)
    brand = Column(String, nullable=True)
    county = Column(String, nullable=True)
    scan_status = Column(String, nullable=True)
    scanned_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "scan_event_id", name="uq_bottle_reports_user_scan"),
        CheckConstraint(
            f"reason IN {REPORT_REASONS}",
            name="ck_bottle_reports_reason",
        ),
        Index(
            "ix_bottle_reports_manufacturer_created",
            "manufacturer_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_bottle_reports_user_created",
            "user_id",
            text("created_at DESC"),
        ),
    )