from datetime import date as date_type, datetime, timedelta, timezone
from typing import List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TimeWindow = Literal["morning", "afternoon", "evening", "night", "late_night"]
DrinkType = Literal["beer", "wine", "spirits", "other"]

# Manual entry is gone. Every session originates from a scan, so the source
# is no longer a choice the client gets to make.
SourceType = Literal["scan"]

# One scan is one bottle, recorded as one item in one session. These are not
# arbitrary ceilings, they are the only shape the app can produce, and a
# request outside them is a client that has been tampered with.
MAX_SESSIONS_PER_BATCH = 1

# A log cannot predate the app or happen tomorrow. One day of slack absorbs
# device clocks and timezone edges.
EARLIEST_LOG = date_type(2024, 1, 1)


def _check_log_date(value: str) -> str:
    try:
        parsed = date_type.fromisoformat(value)
    except ValueError:
        raise ValueError("log_date must be YYYY-MM-DD")

    if parsed < EARLIEST_LOG:
        raise ValueError("log_date is before this app existed")
    if parsed > date_type.today() + timedelta(days=1):
        raise ValueError("log_date cannot be in the future")
    return value


class SessionItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    drink_type: DrinkType
    # One scan, one bottle. Anything else means the client invented a number.
    quantity: Literal[1] = 1
    # A session with no scan behind it can no longer exist, so this is the
    # link that makes the record trustworthy rather than an optional extra.
    scan_event_id: str = Field(min_length=1, max_length=36)


class CreateSessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    occurred_at: Optional[datetime] = None
    log_date: Optional[str] = None
    time_window: TimeWindow
    source: SourceType = "scan"
    items: List[SessionItemPayload] = Field(min_length=1, max_length=1)

    @field_validator("log_date")
    @classmethod
    def validate_log_date(cls, value: Optional[str]) -> Optional[str]:
        return _check_log_date(value) if value else value

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return value

        # Naive timestamps from older clients are read as UTC rather than
        # rejected, so the comparison below is always like for like.
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        if moment.date() < EARLIEST_LOG:
            raise ValueError("occurred_at is before this app existed")
        if moment > datetime.now(timezone.utc) + timedelta(days=1):
            raise ValueError("occurred_at cannot be in the future")
        return value

    @model_validator(mode="after")
    def validate_time_source(self):
        if self.occurred_at is None and not self.log_date:
            raise ValueError("Provide either occurred_at or log_date")
        return self


class BatchCreateSessionsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: List[CreateSessionPayload] = Field(
        min_length=1, max_length=MAX_SESSIONS_PER_BATCH
    )


class UpdateSessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    occurred_at: Optional[datetime] = None
    time_window: Optional[TimeWindow] = None
    items: Optional[List[SessionItemPayload]] = Field(default=None, max_length=1)