from datetime import datetime, timedelta, date
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import joinedload

from core.database import SessionLocal
from core.security import get_current_user_id
from drinks.session_models import DrinkSession

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _parse_month_str(month: str) -> date:
    # month = "YYYY-MM"
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
    Returns sparse map of dates with drinking activity:
      {
        "YYYY-MM-DD": { "hasDrinking": bool, "totalQuantity": int, "sessionCount": int }
      }
    """
    db = SessionLocal()
    try:
        start = _parse_month_str(month)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)  # next month

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

            # Sum quantities for the day
            day_qty = 0
            for it in (s.items or []):
                if it.quantity:
                    day_qty += int(it.quantity)

            marks[k]["totalQuantity"] += day_qty
            if marks[k]["sessionCount"] > 0 or marks[k]["totalQuantity"] > 0:
                marks[k]["hasDrinking"] = True

        return marks
    finally:
        db.close()