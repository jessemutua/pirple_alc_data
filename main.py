import json
from sqlalchemy import create_engine, Column, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from fastapi import FastAPI, HTTPException, status, Header
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional, Union
from datetime import datetime
import uuid
import json
import os

API_SECRET = os.getenv("API_SECRET", "pirple_mvp_secret_2026_change_me")

app = FastAPI(
    title="Pirple Backend MVP",
    description="Privacy-first event ingestion API for policy-grade alcohol consumption data",
    version="0.1.0"
)
# === DATABASE SETUP ===
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set - check Render environment variables")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class EventLog(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    received_at = Column(DateTime, default=datetime.utcnow)
    event_data = Column(JSONB, nullable=False)

# Create the table
Base.metadata.create_all(bind=engine)
# --- Enums and literal types from the architecture ---
UserMode = Literal["tracking", "sobriety"]
DrinkCategory = Literal["beer", "wine", "spirits", "other"]
QuantityBucket = Literal["1-2", "3-4", "5-6", "7+"]
TimeWindow = Literal["afternoon", "evening", "night", "late_night"]
MoodValence = Literal["very_negative", "negative", "neutral", "positive", "very_positive"]
Platform = Literal["ios", "android"]
EventType = Literal["check_in_created", "mode_changed", "consent_updated"]

# --- Base event envelope ---
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
            raise ValueError("Events can only be ingested if data_contribution is true")
        return v

# --- Specific payloads ---
class CheckInPayload(BaseModel):
    mode: UserMode
    date_local: str  # YYYY-MM-DD
    consumption: dict  # Will validate inside the full event
    mood: dict
    notes_present: bool

class ModeChangedPayload(BaseModel):
    previous_mode: UserMode
    new_mode: UserMode

class ConsentUpdatedPayload(BaseModel):
    data_contribution: bool
    reason: Literal["initial", "user_change"]

# --- Full event models ---
class CheckInCreatedEvent(BaseEvent):
    event_type: Literal["check_in_created"] = "check_in_created"
    payload: dict  # We'll accept raw dict for now, refine later

class ModeChangedEvent(BaseEvent):
    event_type: Literal["mode_changed"] = "mode_changed"
    payload: ModeChangedPayload

class ConsentUpdatedEvent(BaseEvent):
    event_type: Literal["consent_updated"] = "consent_updated"
    payload: ConsentUpdatedPayload

# Union of all allowed events
AllowedEvent = Union[CheckInCreatedEvent, ModeChangedEvent, ConsentUpdatedEvent]

@app.get("/")
def read_root():
    return {"message": "Pirple Backend is running! 👋"}

@app.post("/events")
async def ingest_event(
    event: AllowedEvent,
    x_api_secret: str = Header(None, alias="X-API-Secret")
):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing API secret")
    db = SessionLocal()
    try:
        db_event = EventLog(event_data=event.model_dump())
        db.add(db_event)
        db.commit()
        db.refresh(db_event)

        print("\n=== EVENT SUCCESSFULLY SAVED TO DATABASE ===")
        print(json.dumps(event.model_dump(), indent=2, default=str))
        print("==========================================\n")

        return {
            "status": "accepted",
            "event_id": event.event_id,
            "database_id": db_event.id,
            "saved_at": db_event.received_at.isoformat()
        }
    except Exception as e:
        db.rollback()
        print(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save event")
    finally:
        db.close()