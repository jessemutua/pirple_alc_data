from datetime import datetime, date, time, timezone
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import joinedload

from core.database import SessionLocal
from core.security import get_current_user_id
from drinks.session_models import DrinkSession, DrinkSessionItem
from drinks.session_schemas import (
    CreateSessionPayload,
    BatchCreateSessionsPayload,
    UpdateSessionPayload,
)
from drinks.scan_models import ScanEvent
router = APIRouter(prefix="/sessions", tags=["sessions"])


DEFAULT_HOURS = {
    "morning": 9,
    "afternoon": 15,
    "evening": 20,
    "night": 23,
    "late_night": 1,
}


def _parse_date_str(d: str) -> date:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")


def _derive_occurred_at(log_date: date, time_window: str) -> datetime:
    hour = DEFAULT_HOURS.get(time_window, 20)
    # Use UTC for MVP consistency
    return datetime.combine(log_date, time(hour=hour, minute=0, second=0, tzinfo=timezone.utc))

def _resolve_item_auth(db, scan_event_id: str | None) -> tuple[str | None, str]:
    """
    Given an item's scan_event_id (if any), looks up the real ScanEvent
    and returns (product_ref, auth_status) to store on the item —
    never trusting a client-supplied auth_status directly.
    """
    if not scan_event_id:
        return None, "unknown"

    event = db.query(ScanEvent).filter(ScanEvent.id == scan_event_id).first()
    if not event:
        # client sent a scan_event_id that doesn't exist — don't trust it
        return None, "unknown"

    return event.gtin or event.barcode_raw, event.combined_auth_status


def _serialize_session(s: DrinkSession) -> dict:
    return {
        "id": s.id,
        "log_date": s.log_date.isoformat(),
        "occurred_at": s.occurred_at.isoformat(),
        "time_window": s.time_window,
        "source": s.source,
        "notes": s.notes,
        "items": [
            {
                "id": i.id,
                "drink_type": i.drink_type,
                "quantity": i.quantity,
                "product_ref": i.product_ref,
                "auth_status": i.auth_status,
                "scan_event_id": i.scan_event_id,
            }
            for i in (s.items or [])
        ],
    }


def _day_totals(sessions: List[DrinkSession]) -> dict:
    by_type: Dict[str, int] = {"beer": 0, "wine": 0, "spirits": 0, "other": 0}
    total_qty = 0

    for s in sessions:
        for it in (s.items or []):
            qty = int(it.quantity or 0)
            total_qty += qty
            k = (it.drink_type or "other").lower()
            if k not in by_type:
                k = "other"
            by_type[k] += qty

    session_count = len(sessions)
    has_drinking = session_count > 0 or total_qty > 0

    return {
        "totalQuantity": total_qty,
        "byDrinkType": by_type,
        "sessionCount": session_count,
        "hasDrinking": has_drinking,
    }


@router.post("")
def create_session(payload: CreateSessionPayload, user_id: str = Depends(get_current_user_id)):
    db = SessionLocal()
    try:
        with db.begin():
            if payload.occurred_at is not None:
                occurred_at = payload.occurred_at
                # Ensure timezone-aware; if naive, assume UTC
                if occurred_at.tzinfo is None:
                    occurred_at = occurred_at.replace(tzinfo=timezone.utc)
                log_date = occurred_at.date()
            else:
                log_date = _parse_date_str(payload.log_date)  # type: ignore[arg-type]
                occurred_at = _derive_occurred_at(log_date, payload.time_window)

            s = DrinkSession(
                user_id=user_id,
                occurred_at=occurred_at,
                log_date=log_date,
                time_window=payload.time_window,
                source=payload.source or "manual",
                notes=payload.notes,
            )
            db.add(s)
            db.flush()

            for it in payload.items:
                product_ref, auth_status = _resolve_item_auth(db, it.scan_event_id)
                db.add(
                    DrinkSessionItem(
                        session_id=s.id,
                        drink_type=it.drink_type,
                        quantity=it.quantity,
                        product_ref=product_ref,
                        auth_status=auth_status,
                        scan_event_id=it.scan_event_id,
                    )
                )

        # reload with items
        s2 = (
            db.query(DrinkSession)
            .options(joinedload(DrinkSession.items))
            .filter(DrinkSession.id == s.id)
            .first()
        )
        return {"session": _serialize_session(s2)}  # type: ignore[arg-type]
    finally:
        db.close()


@router.post("/batch")
def create_sessions_batch(payload: BatchCreateSessionsPayload, user_id: str = Depends(get_current_user_id)):
    db = SessionLocal()
    created_ids: List[str] = []
    try:
        with db.begin():
            for p in payload.sessions:
                if p.occurred_at is not None:
                    occurred_at = p.occurred_at
                    if occurred_at.tzinfo is None:
                        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
                    log_date = occurred_at.date()
                else:
                    log_date = _parse_date_str(p.log_date)  # type: ignore[arg-type]
                    occurred_at = _derive_occurred_at(log_date, p.time_window)

                s = DrinkSession(
                    user_id=user_id,
                    occurred_at=occurred_at,
                    log_date=log_date,
                    time_window=p.time_window,
                    source=p.source or "manual",
                    notes=p.notes,
                )
                db.add(s)
                db.flush()

                for it in p.items:
                    product_ref, auth_status = _resolve_item_auth(db, it.scan_event_id)
                    db.add(
                        DrinkSessionItem(
                            session_id=s.id,
                            drink_type=it.drink_type,
                            quantity=it.quantity,
                            product_ref=product_ref,
                            auth_status=auth_status,
                            scan_event_id=it.scan_event_id,
                        )
                    )

                created_ids.append(s.id)

        sessions = (
            db.query(DrinkSession)
            .options(joinedload(DrinkSession.items))
            .filter(DrinkSession.user_id == user_id)
            .filter(DrinkSession.id.in_(created_ids))
            .order_by(DrinkSession.log_date.asc(), DrinkSession.occurred_at.asc())
            .all()
        )

        affected_days = sorted({s.log_date.isoformat() for s in sessions})
        return {
            "created": [_serialize_session(s) for s in sessions],
            "affectedDays": affected_days,
        }
    finally:
        db.close()


@router.put("/{session_id}")
def update_session(session_id: str, payload: UpdateSessionPayload, user_id: str = Depends(get_current_user_id)):
    db = SessionLocal()
    try:
        with db.begin():
            s = (
                db.query(DrinkSession)
                .options(joinedload(DrinkSession.items))
                .filter(DrinkSession.id == session_id)
                .filter(DrinkSession.user_id == user_id)
                .first()
            )
            if not s:
                raise HTTPException(status_code=404, detail="Session not found")

            if payload.occurred_at is not None:
                occurred_at = payload.occurred_at
                if occurred_at.tzinfo is None:
                    occurred_at = occurred_at.replace(tzinfo=timezone.utc)
                s.occurred_at = occurred_at
                s.log_date = occurred_at.date()

            if payload.time_window is not None:
                s.time_window = payload.time_window

            if payload.source is not None:
                s.source = payload.source

            if payload.notes is not None:
                s.notes = payload.notes

            # Replace items if provided
            if payload.items is not None:
                # delete existing items
                db.query(DrinkSessionItem).filter(DrinkSessionItem.session_id == s.id).delete(
                    synchronize_session=False
                )
                # insert new
                for it in payload.items:
                    product_ref, auth_status = _resolve_item_auth(db, it.scan_event_id)
                    db.add(
                        DrinkSessionItem(
                            session_id=s.id,
                            drink_type=it.drink_type,
                            quantity=it.quantity,
                            product_ref=product_ref,
                            auth_status=auth_status,
                            scan_event_id=it.scan_event_id,
                        )
                    )

        s2 = (
            db.query(DrinkSession)
            .options(joinedload(DrinkSession.items))
            .filter(DrinkSession.id == session_id)
            .filter(DrinkSession.user_id == user_id)
            .first()
        )
        return {"session": _serialize_session(s2)}  # type: ignore[arg-type]
    finally:
        db.close()


@router.delete("/{session_id}")
def delete_session(session_id: str, user_id: str = Depends(get_current_user_id)):
    db = SessionLocal()
    try:
        with db.begin():
            s = (
                db.query(DrinkSession)
                .filter(DrinkSession.id == session_id)
                .filter(DrinkSession.user_id == user_id)
                .first()
            )
            if not s:
                raise HTTPException(status_code=404, detail="Session not found")

            db.delete(s)

        return {"ok": True}
    finally:
        db.close()


@router.get("/day")
def get_sessions_for_day(
    date_str: str = Query(..., alias="date"),
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        d = _parse_date_str(date_str)

        sessions = (
            db.query(DrinkSession)
            .options(joinedload(DrinkSession.items))
            .filter(DrinkSession.user_id == user_id)
            .filter(DrinkSession.log_date == d)
            .order_by(DrinkSession.occurred_at.asc())
            .all()
        )

        return {
            "date": d.isoformat(),
            "sessions": [_serialize_session(s) for s in sessions],
            "dayTotals": _day_totals(sessions),
        }
    finally:
        db.close()