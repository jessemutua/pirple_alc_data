import uuid

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Date,
    Integer,
    ForeignKey,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


TIME_WINDOWS = ("morning", "afternoon", "evening", "night", "late_night")
SOURCES = ("manual", "scan")
DRINK_TYPES = ("beer", "wine", "spirits", "other")
AUTH_STATUSES = ("unknown", "verified", "suspicious")


class DrinkSession(Base):
    __tablename__ = "drink_sessions"

    id = Column(String, primary_key=True, default=uuid_str)
    user_id = Column(String, nullable=False)

    occurred_at = Column(DateTime(timezone=True), nullable=False)
    log_date = Column(Date, nullable=False)

    time_window = Column(String, nullable=False)
    source = Column(String, nullable=False, default="manual")
    notes = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    items = relationship(
        "DrinkSessionItem",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            f"time_window IN {TIME_WINDOWS}",
            name="ck_drink_sessions_time_window",
        ),
        CheckConstraint(
            f"source IN {SOURCES}",
            name="ck_drink_sessions_source",
        ),
        Index("ix_drink_sessions_user_log_date", "user_id", "log_date"),
        Index("ix_drink_sessions_user_occurred_at", "user_id", "occurred_at"),
    )


class DrinkSessionItem(Base):
    __tablename__ = "drink_session_items"

    id = Column(String, primary_key=True, default=uuid_str)

    session_id = Column(
        String,
        ForeignKey("drink_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    drink_type = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)

    product_ref = Column(String, nullable=True)
    auth_status = Column(String, nullable=False, default="unknown")
    scan_event_id = Column(String, ForeignKey("scan_events.id"), nullable=True)
        
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    session = relationship("DrinkSession", back_populates="items")

    __table_args__ = (
        CheckConstraint(
            f"drink_type IN {DRINK_TYPES}",
            name="ck_drink_session_items_drink_type",
        ),
        CheckConstraint(
            f"auth_status IN {AUTH_STATUSES}",
            name="ck_drink_session_items_auth_status",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="ck_drink_session_items_quantity_nonneg",
        ),
        Index("ix_drink_session_items_session_id", "session_id"),
    )