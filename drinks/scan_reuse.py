# drinks/scan_reuse.py
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func

from drinks.scan_models import ScanEvent

SEVEN_DAYS = timedelta(days=7)
TWENTY_FOUR_HOURS = timedelta(hours=24)


def check_reuse(
    db: Session,
    serial: str,
    current_user_id: str,
) -> Tuple[str, Optional[str], Optional[datetime], Optional[datetime], Optional[str]]:
    """
    Looks at this serial's scan history and applies the locked reuse rule.

    Returns a tuple of:
      (auth_status, auth_reason, first_scan_at, prior_scan_at, prior_scan_user_id)

    The last three values are the history snapshot to store on the new
    ScanEvent row itself, so future scans of this serial don't need to
    re-query the full history every time.
    """
    # Pull this serial's earliest scan (for the 7-day ceiling) in one query.
    first_scan_at = db.query(func.min(ScanEvent.created_at)).filter(
        ScanEvent.serial == serial
    ).scalar()

    # Pull the single most recent scan of this serial (for the 24h check).
    prior_event = (
        db.query(ScanEvent)
        .filter(ScanEvent.serial == serial)
        .order_by(ScanEvent.created_at.desc())
        .first()
    )

    now = datetime.now(timezone.utc)

    # No history at all — first time this serial has ever been scanned.
    if first_scan_at is None or prior_event is None:
        return "verified", None, now, None, None

    # Rule 1 — 7-day ceiling, applies regardless of who's scanning.
    if now - first_scan_at >= SEVEN_DAYS:
        days_ago = (now - first_scan_at).days
        reason = f"first scanned {days_ago} days ago"
        return "suspicious", reason, first_scan_at, prior_event.created_at, prior_event.user_id

    # Rule 2 — different user, 24h+ since the last scan.
    is_different_user = prior_event.user_id != current_user_id
    time_since_prior = now - prior_event.created_at
    if is_different_user and time_since_prior >= TWENTY_FOUR_HOURS:
        hours_ago = int(time_since_prior.total_seconds() // 3600)
        reason = f"originally scanned by another user {hours_ago}h ago"
        return "suspicious", reason, first_scan_at, prior_event.created_at, prior_event.user_id

    # Rule 3 — everything else is fine.
    return "verified", None, first_scan_at, prior_event.created_at, prior_event.user_id