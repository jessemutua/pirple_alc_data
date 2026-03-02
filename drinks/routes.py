from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi import HTTPException

from drinks.models import DrinkLog
from drinks.schemas import DrinkLogPayload
from core.database import SessionLocal
from core.deps import get_current_user_id

router = APIRouter(prefix="/drink-logs", tags=["drinks"])


@router.post("")
def ingest_drink_log(
    payload: DrinkLogPayload,
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        existing = (
            db.query(DrinkLog)
            .filter(DrinkLog.user_id == user_id)
            .filter(DrinkLog.date == payload.date)
            .first()
        )

        if existing:
            for k, v in payload.dict().items():
                setattr(existing, k, v)
            db.commit()
            return {"log_id": existing.id}

        log = DrinkLog(user_id=user_id, **payload.dict())
        db.add(log)
        db.commit()
        db.refresh(log)

        return {"log_id": log.id}
    finally:
        db.close()


@router.get("/month")
def get_month_logs(
    month: str,
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        start = datetime.strptime(month + "-01", "%Y-%m-%d")
        end = (start + timedelta(days=32)).replace(day=1)

        logs = (
            db.query(DrinkLog)
            .filter(DrinkLog.user_id == user_id)
            .filter(DrinkLog.date >= start.strftime("%Y-%m-%d"))
            .filter(DrinkLog.date < end.strftime("%Y-%m-%d"))
            .all()
        )

        result = {}
        for log in logs:
            result[log.date] = {
                "drank": log.drank,
                "drink_count": log.drink_count,
            }

        return result
    finally:
        db.close()

@router.get("/day")
def get_day_log(
    date: str,
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        log = (
            db.query(DrinkLog)
            .filter(DrinkLog.user_id == user_id)
            .filter(DrinkLog.date == date)
            .first()
        )

        if not log:
            # Frontend will treat this as "no log exists"
            raise HTTPException(status_code=404, detail="No log for that date")

        return {
            "date": log.date,
            "drank": log.drank,
            "drink_count": log.drink_count,
            "drinks": log.drinks,
            "time_windows": log.time_windows,
            "notes": log.notes,
            # IMPORTANT: do NOT return user_id if you want non-PII responses
        }
    finally:
        db.close()