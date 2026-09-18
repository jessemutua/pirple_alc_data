from datetime import date as date_type, timedelta

from pydantic import BaseModel, ConfigDict, field_validator

EARLIEST_LOG = date_type(2024, 1, 1)


class UpsertSoberDayPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date: str  # YYYY-MM-DD

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            parsed = date_type.fromisoformat(value)
        except ValueError:
            raise ValueError("date must be YYYY-MM-DD")

        if parsed < EARLIEST_LOG:
            raise ValueError("date is before this app existed")
        if parsed > date_type.today() + timedelta(days=1):
            raise ValueError("date cannot be in the future")
        return value


class SoberDayResponse(BaseModel):
    date: str
    logged: bool  # True = sober day exists, False = deleted