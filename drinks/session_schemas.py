from datetime import date as date_type, datetime, timedelta, timezone
from typing import List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TimeWindow = Literal["morning", "afternoon", "evening", "night", "late_night"]
DrinkType = Literal["beer", "wine", "spirits", "other"]
SourceType = Literal["manual", "scan"]

# These mirror what the app can actually produce, so anything outside them is
# a client that has been tampered with, not a user doing something unusual.
#
#   quantity : the highest bucket, "7+", resolves to 7, and a scan sends 1.
#   items    : one per drink type, and there are four.
#   sessions : one per time-of-day chip, and there are five.
#   notes    : the note field is capped at 100 characters in the form.
#
# Widen these in step with the form, never ahead of it.
MAX_QUANTITY_PER_ITEM = 7
MAX_ITEMS_PER_SESSION = 4
MAX_SESSIONS_PER_BATCH = 5
MAX_NOTE_LEN = 100

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
    # The form drops zero-quantity items before sending, so zero here would
    # mean a row that says nothing.
    quantity: int = Field(ge=1, le=MAX_QUANTITY_PER_ITEM)
    scan_event_id: Optional[str] = Field(default=None, max_length=36)


class CreateSessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    occurred_at: Optional[datetime] = None
    log_date: Optional[str] = None
    time_window: TimeWindow
    source: Optional[SourceType] = "manual"
    notes: Optional[str] = Field(default=None, max_length=MAX_NOTE_LEN)
    items: List[SessionItemPayload] = Field(
        min_length=1, max_length=MAX_ITEMS_PER_SESSION
    )

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
    notes: Optional[str] = Field(default=None, max_length=MAX_NOTE_LEN)
    source: Optional[SourceType] = None
    items: Optional[List[SessionItemPayload]] = Field(
        default=None, max_length=MAX_ITEMS_PER_SESSION
    )