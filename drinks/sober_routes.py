from datetime import datetime, date as date_type

from fastapi import APIRouter, Depends, HTTPException

from core.database import SessionLocal
from core.security import get_current_user_id
from drinks.sober_models import SoberDay
from drinks.sober_schemas import UpsertSoberDayPayload, SoberDayResponse

router = APIRouter(prefix="/sober-days", tags=["sober-days"])


def _parse_date_str(d: str) -> date_type:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")


def _is_future(d: date_type) -> bool:
    return d > date_type.today()


@router.post("", response_model=SoberDayResponse)
def upsert_sober_day(
    payload: UpsertSoberDayPayload,
    user_id: str = Depends(get_current_user_id),
):
    """
    Mark a date as sober. Idempotent — safe to call multiple times.
    """
    log_date = _parse_date_str(payload.date)

    if _is_future(log_date):
        raise HTTPException(status_code=400, detail="Cannot log future dates")

    db = SessionLocal()
    try:
        with db.begin():
            existing = (
                db.query(SoberDay)
                .filter(SoberDay.user_id == user_id)
                .filter(SoberDay.log_date == log_date)
                .first()
            )

            if not existing:
                db.add(SoberDay(user_id=user_id, log_date=log_date))

        return SoberDayResponse(date=payload.date, logged=True)
    finally:
        db.close()


@router.delete("/{date}", response_model=SoberDayResponse)
def delete_sober_day(
    date: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Unmark a sober day. Idempotent — safe to call even if row doesn't exist.
    """
    log_date = _parse_date_str(date)

    db = SessionLocal()
    try:
        with db.begin():
            row = (
                db.query(SoberDay)
                .filter(SoberDay.user_id == user_id)
                .filter(SoberDay.log_date == log_date)
                .first()
            )
            if row:
                db.delete(row)

        return SoberDayResponse(date=date, logged=False)
    finally:
        db.close()