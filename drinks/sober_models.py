import uuid

from sqlalchemy import (
    Column,
    String,
    Date,
    DateTime,
    Index,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from core.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


class SoberDay(Base):
    """
    Explicit record that a user marked a specific calendar date as sober.
    One row per (user_id, date) — enforced by unique constraint.
    """
    __tablename__ = "sober_days"

    id = Column(String, primary_key=True, default=uuid_str)
    user_id = Column(String, nullable=False)
    log_date = Column(Date, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_sober_days_user_date"),
        Index("ix_sober_days_user_log_date", "user_id", "log_date"),
    )