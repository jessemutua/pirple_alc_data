from pydantic import BaseModel


class UpsertSoberDayPayload(BaseModel):
    date: str  # YYYY-MM-DD


class SoberDayResponse(BaseModel):
    date: str
    logged: bool  # True = sober day exists, False = deleted