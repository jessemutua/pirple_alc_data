import os
import json
import uuid
from datetime import datetime
from typing import Literal, Optional, Union

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field, validator

from sqlalchemy import create_engine, Column, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# === CONFIGURATION ===
API_SECRET = os.getenv("API_SECRET")
if not API_SECRET:
    raise RuntimeError("API_SECRET is not set")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# Normalize Render Postgres URL
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://", "postgresql+psycopg2://", 1
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# === DATABASE MODEL ===
class EventLog(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    event_data = Column(JSONB, nullable=False)

# === APP ===
app = FastAPI(
    title="Pirple Backend MVP",
    description="Privacy-first event ingestion API for policy-grade alcohol consumption data",
    version="0.1.0",
)

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

# === SCHEMA ===
UserMode = Literal["tracking", "sobriety"]
DrinkCategory = Literal["beer", "wine", "spirits", "other"]
QuantityBucket = Literal["1-2", "3-4", "5-6", "7+"]
TimeWindow = Literal["afternoon", "evening", "night", "late_night"]
MoodValence = Literal["very_negative", "negative", "neutral", "positive", "very_positive"]
Platform = Literal["ios", "android"]
EventType = Literal["check_in_created", "mode_changed", "consent_updated"]

class ConsentState(BaseModel):
    data_contribution: bool
    version: str = "1.0"

class ClientInfo(BaseModel):
    platform: Platform
    app_version: str

class GeoInfo(BaseModel):
    country: str = "KE"
    county: Optional[str] = None

class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    event_version: str = "1.0"
    event_time_utc: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    anonymous_user_id: str
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    consent_state: ConsentState
    client: ClientInfo
    geo: GeoInfo

    @validator("consent_state")
    def consent_must_be_true(cls, v):
        if not v.data_contribution:
            raise ValueError("data_contribution must be true")
        return v

# === PAYLOADS ===
class Consumption(BaseModel):
    occurred: bool
    drink_category: Optional[DrinkCategory] = None
    quantity_bucket: Optional[QuantityBucket] = None
    time_window: Optional[TimeWindow] = None

class Mood(BaseModel):
    valence: MoodValence

class CheckInPayload(BaseModel):
    mode: UserMode
    date_local: str
    consumption: Consumption
    mood: Mood
    notes_present: bool

class ModeChangedPayload(BaseModel):
    previous_mode: UserMode
    new_mode: UserMode

class ConsentUpdatedPayload(BaseModel):
    data_contribution: bool
    reason: Literal["initial", "user_change"]

# === EVENTS ===
class CheckInCreatedEvent(BaseEvent):
    event_type: Literal["check_in_created"] = "check_in_created"
    payload: CheckInPayload

class ModeChangedEvent(BaseEvent):
    event_type: Literal["mode_changed"] = "mode_changed"
    payload: ModeChangedPayload

class ConsentUpdatedEvent(BaseEvent):
    event_type: Literal["consent_updated"] = "consent_updated"
    payload: ConsentUpdatedPayload

AllowedEvent = Union[
    CheckInCreatedEvent,
    ModeChangedEvent,
    ConsentUpdatedEvent,
]

# === ROUTES ===
@app.get("/")
def read_root():
    return {"message": "Pirple Backend is running"}

@app.post("/events")
async def ingest_event(
    event: AllowedEvent,
    x_api_secret: Optional[str] = Header(None, alias="X-API-Secret"),
):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid API secret")

    db = SessionLocal()
    try:
        db_event = EventLog(event_data=event.dict())
        db.add(db_event)
        db.commit()
        db.refresh(db_event)

        return {
            "status": "accepted",
            "event_id": event.event_id,
            "database_id": db_event.id,
            "saved_at": db_event.received_at.isoformat(),
        }
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save event")
    finally:
        db.close()
