from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import joinedload

from analytics.service import build_user_analytics
from core.database import SessionLocal
from core.security import get_current_user_id
from drinks.session_models import DrinkSession
from drinks.sober_models import SoberDay

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
def get_analytics(
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        if days < 1:
            days = 1

        to_date = date_type.today()
        from_date = to_date - timedelta(days=days - 1)

        sessions = (
            db.query(DrinkSession)
            .options(joinedload(DrinkSession.items))
            .filter(DrinkSession.user_id == user_id)
            .filter(DrinkSession.log_date >= from_date)
            .filter(DrinkSession.log_date <= to_date)
            .order_by(DrinkSession.log_date.asc(), DrinkSession.occurred_at.asc())
            .all()
        )

        sober_rows = (
            db.query(SoberDay)
            .filter(SoberDay.user_id == user_id)
            .filter(SoberDay.log_date >= from_date)
            .filter(SoberDay.log_date <= to_date)
            .all()
        )
        sober_dates = {row.log_date for row in sober_rows}

        return build_user_analytics(
            sessions=sessions,
            sober_dates=sober_dates,
            from_date=from_date,
            to_date=to_date,
            requested_days=days,
        )
    finally:
        db.close()