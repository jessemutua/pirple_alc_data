from datetime import datetime, timedelta, date
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import joinedload

from core.database import SessionLocal
from core.security import get_current_user_id
from drinks.session_models import DrinkSession
from drinks.sober_models import SoberDay

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _parse_month_str(month: str) -> date:
    try:
        return datetime.strptime(month + "-01", "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM")


@router.get("/month")
def get_month_marks(
    month: str = Query(...),
    user_id: str = Depends(get_current_user_id),
):
    """
    Returns a map of all explicitly logged dates for the month:
      {
        "YYYY-MM-DD": {
          "hasDrinking": bool,
          "totalQuantity": int,
          "sessionCount": int
        }
      }

    - Drinking days: hasDrinking=True, totalQuantity > 0
    - Sober days:    hasDrinking=False, totalQuantity=0, sessionCount=0
    - Unlogged days: absent from the map entirely
    """
    db = SessionLocal()
    try:
        start = _parse_month_str(month)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)

        # --- drinking days ---
        sessions = (
            db.query(DrinkSession)
            .options(joinedload(DrinkSession.items))
            .filter(DrinkSession.user_id == user_id)
            .filter(DrinkSession.log_date >= start)
            .filter(DrinkSession.log_date < end)
            .order_by(DrinkSession.log_date.asc())
            .all()
        )

        marks: Dict[str, dict] = {}

        for s in sessions:
            k = s.log_date.isoformat()
            if k not in marks:
                marks[k] = {"hasDrinking": False, "totalQuantity": 0, "sessionCount": 0}

            marks[k]["sessionCount"] += 1

            day_qty = 0
            for it in (s.items or []):
                if it.quantity:
                    day_qty += int(it.quantity)

            marks[k]["totalQuantity"] += day_qty

            if marks[k]["sessionCount"] > 0 or marks[k]["totalQuantity"] > 0:
                marks[k]["hasDrinking"] = True

        # --- sober days ---
        # Only add sober entries for dates with no drinking sessions.
        # If both somehow exist, drinking takes priority.
        sober_rows = (
            db.query(SoberDay)
            .filter(SoberDay.user_id == user_id)
            .filter(SoberDay.log_date >= start)
            .filter(SoberDay.log_date < end)
            .all()
        )

        for row in sober_rows:
            k = row.log_date.isoformat()
            if k not in marks:
                marks[k] = {
                    "hasDrinking": False,
                    "totalQuantity": 0,
                    "sessionCount": 0,
                }

        return marks
    finally:
        db.close()