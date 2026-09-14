# reporting/models.py
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.sql import func

from core.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


# admin can manage users for their manufacturer; viewer can only read.
MANUFACTURER_ROLES = ("admin", "viewer")


class ManufacturerUser(Base):
    """
    A login belonging to a manufacturer, kept separate from consumer users.

    Consumer accounts and commercial accounts have different lifecycles and
    different scopes — one table for both eventually leaks one into the other.
    """

    __tablename__ = "manufacturer_users"

    id = Column(String, primary_key=True, default=uuid_str)

    # The tenancy boundary. Every reporting query filters on this.
    manufacturer_id = Column(
        String, ForeignKey("manufacturers.id"), nullable=False
    )

    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)

    full_name = Column(String, nullable=True)
    role = Column(String, nullable=False, default="viewer")

    # Revoke access without deleting the row, so the audit trail survives.
    is_active = Column(Boolean, nullable=False, default=True)

    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_manufacturer_users_manufacturer_id", "manufacturer_id"),
    )