# drinks/activity_routes.py
import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status as http
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.security import get_current_user_id
from drinks.drink_types import normalise_drink_type
from drinks.report_models import MAX_NOTE_LEN, BottleReport
from drinks.scan_models import ScanEvent
from drinks.session_models import DrinkSession, DrinkSessionItem
from products.models import Product, ProductSerial

router = APIRouter(prefix="/activity", tags=["activity"])

# A report is about how a bottle turned out, which is known within days of
# opening it. After a month the memory is unreliable and the stock has moved.
REPORT_WINDOW_DAYS = 30

# Enough for anyone with a genuine run of bad bottles, too few to flood a
# manufacturer from one account.
DAILY_REPORT_CAP = 5

# The consent line the app shows before sending. When its wording changes,
# this changes with it, and older apps are asked to update rather than
# sending under terms the person never saw.
CONSENT_VERSION = "2026-09-22"

DEFAULT_PAGE = 20
MAX_PAGE = 50

# Mirrors REPORT_REASONS in drinks/report_models.py and the database check.
ReportReason = Literal["taste_smell_wrong", "felt_unwell", "other"]

# Everything below a space except newline, plus DEL. Invisible characters in
# a note are never intended, and some are used to break layouts downstream.
_CONTROL_CHARS = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _aware(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=timezone.utc)


def _cursor_for(event: ScanEvent) -> str:
    """Microseconds since the epoch plus the id: exact, and URL-safe."""
    micros = (_aware(event.created_at) - _EPOCH) // timedelta(microseconds=1)
    return f"{micros}_{event.id}"


def _parse_cursor(raw: str):
    try:
        micros_raw, event_id = raw.split("_", 1)
        moment = _EPOCH + timedelta(microseconds=int(micros_raw))
    except (ValueError, OverflowError):
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Invalid cursor")
    if not event_id or len(event_id) > 36:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Invalid cursor")
    return moment, event_id


def _item(event, product_name, logged_type, opened, report, now) -> dict:
    scanned_at = _aware(event.created_at)
    deadline = scanned_at + timedelta(days=REPORT_WINDOW_DAYS)

    has_product = bool(event.brand or product_name)

    return {
        "scan_event_id": event.id,
        "scanned_at": scanned_at.isoformat(),
        "status": event.combined_auth_status,
        "reason": event.auth_reason,
        "county": event.county,
        "has_code": bool(event.serial),
        "product": (
            {
                "brand": event.brand,
                "name": product_name,
                "drink_type": normalise_drink_type(event.category),
            }
            if has_product
            else None
        ),
        "logged": logged_type is not None,
        "logged_drink_type": logged_type,
        "opened": opened,
        "report": (
            {
                "reason": report.reason,
                "reported_at": _aware(report.created_at).isoformat(),
            }
            if report
            else None
        ),
        "can_report": report is None and now < deadline,
        "report_deadline": deadline.isoformat(),
    }


def _build_items(db: Session, user_id: str, rows) -> list:
    """Everything a page needs in three extra queries, not one per row."""
    ids = [event.id for event, _ in rows]
    if not ids:
        return []

    logged = dict(
        db.query(DrinkSessionItem.scan_event_id, DrinkSessionItem.drink_type)
        .join(DrinkSession, DrinkSession.id == DrinkSessionItem.session_id)
        .filter(DrinkSession.user_id == user_id)
        .filter(DrinkSessionItem.scan_event_id.in_(ids))
        .all()
    )

    reports = {
        r.scan_event_id: r
        for r in db.query(BottleReport)
        .filter(BottleReport.user_id == user_id)
        .filter(BottleReport.scan_event_id.in_(ids))
        .all()
    }

    coded = [(e.gtin, e.serial) for e, _ in rows if e.gtin and e.serial]
    opened_pairs = set()
    if coded:
        opened_pairs = {
            (g, s)
            for g, s in db.query(ProductSerial.gtin14, ProductSerial.serial)
            .filter(ProductSerial.retired_by == user_id)
            .filter(ProductSerial.gtin14.in_({g for g, _ in coded}))
            .filter(ProductSerial.serial.in_({s for _, s in coded}))
            .all()
        }

    now = datetime.now(timezone.utc)
    return [
        _item(
            event,
            product_name,
            logged.get(event.id),
            (event.gtin, event.serial) in opened_pairs,
            reports.get(event.id),
            now,
        )
        for event, product_name in rows
    ]


@router.get("")
def list_activity(
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    before: Optional[str] = Query(None, max_length=64),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """The person's own scans, newest first."""
    query = (
        db.query(ScanEvent, Product.product_name)
        .outerjoin(Product, Product.gtin14 == ScanEvent.gtin)
        .filter(ScanEvent.user_id == user_id)
    )

    if before:
        moment, event_id = _parse_cursor(before)
        query = query.filter(
            or_(
                ScanEvent.created_at < moment,
                and_(ScanEvent.created_at == moment, ScanEvent.id < event_id),
            )
        )

    rows = (
        query.order_by(ScanEvent.created_at.desc(), ScanEvent.id.desc())
        .limit(limit + 1)
        .all()
    )

    has_more = len(rows) > limit
    rows = rows[:limit]

    return {
        "items": _build_items(db, user_id, rows),
        "next_cursor": _cursor_for(rows[-1][0]) if has_more and rows else None,
    }


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: ReportReason
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_LEN)
    consent_version: str = Field(min_length=1, max_length=32)

    @field_validator("note", mode="before")
    @classmethod
    def clean_note(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("note must be text")
        cleaned = _CONTROL_CHARS.sub("", value).strip()
        return cleaned or None


@router.post("/{scan_event_id}/report", status_code=http.HTTP_201_CREATED)
def report_scan(
    payload: ReportRequest,
    scan_event_id: str = Path(..., min_length=1, max_length=36),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    One person's account of one bottle. Recorded as their report, never as a
    finding about the product, and never shown to anyone as a verdict.
    """
    if payload.consent_version != CONSENT_VERSION:
        raise HTTPException(
            http.HTTP_409_CONFLICT,
            "The reporting terms have changed. Update the app and try again.",
        )

    # Only your own scans. Anyone else's reads as not found, so the route
    # never confirms that a scan exists.
    event = (
        db.query(ScanEvent)
        .filter(ScanEvent.id == scan_event_id)
        .filter(ScanEvent.user_id == user_id)
        .first()
    )
    if event is None:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "Scan not found")

    now = datetime.now(timezone.utc)
    scanned_at = _aware(event.created_at)

    if now - scanned_at > timedelta(days=REPORT_WINDOW_DAYS):
        raise HTTPException(
            http.HTTP_409_CONFLICT,
            f"This scan is more than {REPORT_WINDOW_DAYS} days old and can no longer be reported.",
        )

    already = (
        db.query(BottleReport.id)
        .filter(BottleReport.user_id == user_id)
        .filter(BottleReport.scan_event_id == event.id)
        .first()
    )
    if already:
        raise HTTPException(http.HTTP_409_CONFLICT, "You've already reported this scan.")

    sent_today = (
        db.query(func.count(BottleReport.id))
        .filter(BottleReport.user_id == user_id)
        .filter(BottleReport.created_at >= now - timedelta(days=1))
        .scalar()
    )
    if sent_today >= DAILY_REPORT_CAP:
        raise HTTPException(
            http.HTTP_429_TOO_MANY_REQUESTS,
            "You've reached today's report limit. Try again tomorrow.",
        )

    report = BottleReport(
        user_id=user_id,
        scan_event_id=event.id,
        reason=payload.reason,
        note=payload.note,
        consent_version=payload.consent_version,
        manufacturer_id=event.manufacturer_id,
        gtin=event.gtin,
        brand=event.brand,
        county=event.county,
        scan_status=event.combined_auth_status,
        scanned_at=scanned_at,
    )
    db.add(report)

    try:
        db.commit()
    except IntegrityError:
        # Two taps at once. The unique constraint let exactly one through.
        db.rollback()
        raise HTTPException(http.HTTP_409_CONFLICT, "You've already reported this scan.")

    db.refresh(report)

    return {
        "scan_event_id": event.id,
        "report": {
            "reason": report.reason,
            "reported_at": _aware(report.created_at).isoformat(),
        },
    }