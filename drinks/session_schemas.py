from datetime import datetime
from typing import List, Optional, Literal

from pydantic import BaseModel, Field, model_validator


TimeWindow = Literal["morning", "afternoon", "evening", "night", "late_night"]
DrinkType = Literal["beer", "wine", "spirits", "other"]
SourceType = Literal["manual", "scan"]


class SessionItemPayload(BaseModel):
    drink_type: DrinkType
    quantity: int = Field(ge=0)
    scan_event_id: Optional[str] = None


class CreateSessionPayload(BaseModel):
    occurred_at: Optional[datetime] = None
    log_date: Optional[str] = None
    time_window: TimeWindow
    source: Optional[SourceType] = "manual"
    notes: Optional[str] = None
    items: List[SessionItemPayload] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_time_source(self):
        if self.occurred_at is None and not self.log_date:
            raise ValueError("Provide either occurred_at or log_date")
        return self


class BatchCreateSessionsPayload(BaseModel):
    sessions: List[CreateSessionPayload] = Field(min_length=1)


class UpdateSessionPayload(BaseModel):
    occurred_at: Optional[datetime] = None
    time_window: Optional[TimeWindow] = None
    notes: Optional[str] = None
    source: Optional[SourceType] = None
    items: Optional[List[SessionItemPayload]] = None