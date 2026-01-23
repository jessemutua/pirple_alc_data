from datetime import datetime, timedelta
from fastapi import APIRouter, Depends

from analytics.service import build_analytics
from drinks.models import DrinkLog
from core.database import SessionLocal
from core.deps import get_current_user_id

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
def get_analytics(
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        logs = (
            db.query(DrinkLog)
            .filter(DrinkLog.user_id == user_id)
            .filter(DrinkLog.date >= since)
            .order_by(DrinkLog.date.asc())
            .all()
        )

        return build_analytics(logs, days)
    finally:
        db.close()
