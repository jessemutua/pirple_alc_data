from fastapi import APIRouter, Header, HTTPException
import os
from core.database import SessionLocal

router = APIRouter(prefix="/admin", tags=["admin"])

METRICS_TOKEN = os.getenv("METRICS_TOKEN", "")

@router.post("/refresh-metrics")
def refresh_metrics(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "").strip()
    if not token or token != METRICS_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db = SessionLocal()
    try:
        db.execute("SELECT refresh_all_metrics()")
        db.commit()
        return {"ok": True, "message": "Metrics refreshed successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()