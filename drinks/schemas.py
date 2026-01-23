from pydantic import BaseModel
from typing import Optional, Dict, List


class DrinkLogPayload(BaseModel):
    date: str
    drank: bool
    drink_count: Optional[int] = None
    drinks: Optional[Dict[str, int]] = None
    time_windows: Optional[List[str]] = None
    notes: Optional[str] = None
