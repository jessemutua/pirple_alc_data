import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB

from core.database import Base


class DrinkLog(Base):
    __tablename__ = "drink_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    date = Column(String, nullable=False)
    drank = Column(Boolean, nullable=False)
    drink_count = Column(Integer)
    drinks = Column(JSONB)
    time_windows = Column(JSONB)
    notes = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
