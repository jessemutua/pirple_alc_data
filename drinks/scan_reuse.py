# drinks/scan_reuse.py
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from drinks.scan_models import ScanEvent

# How long after a serial's FIRST ever scan it stops being credible,
# and how long after a PRIOR scan by a different user it looks cloned.
# Env-overridable so the rules are testable without waiting real days.
# Defaults are the production values.
FIRST_SCAN_MAX_AGE = timedelta(
    hours=float(os.getenv("SCAN_REUSE_FIRST_SCAN_MAX_AGE_HOURS", "168"))  # 7 days
)
OTHER_USER_MIN_GAP = timedelta(
    hours=float(os.getenv("SCAN_REUSE_OTHER_USER_MIN_GAP_HOURS", "24"))
)


def check_reuse(
    db: Session,
    gtin14: Optional[str],
    serial: str,
    current_user_id: str,
) -> Tuple[str, Optional[str], Optional[datetime], Optional[datetime], Optional[str]]:
    """
    Applies the reuse rules to this serial's scan history.

    Returns:
      (auth_status, auth_reason, first_scan_at, prior_scan_at, prior_scan_user_id)

    The last three are the history snapshot stored on the new ScanEvent, so
    future scans of this serial don't re-query the full history every time.

    Scoped to (gtin, serial): GS1 guarantees serial uniqueness only WITHIN a
    product, so two manufacturers may legitimately issue the same string.
    """
    history = db.query(ScanEvent).filter(ScanEvent.serial == serial)
    if gtin14:
        history = history.filter(ScanEvent.gtin == gtin14)

    # Earliest scan of this serial — the ceiling rule.
    first_scan_at = history.with_entities(func.min(ScanEvent.created_at)).scalar()

    # Most recent scan of this serial — the clone rule.
    prior_event = history.order_by(ScanEvent.created_at.desc()).first()

    now = datetime.now(timezone.utc)

    # No history — first time this serial has ever been seen.
    if first_scan_at is None or prior_event is None:
        return "verified", None, now, None, None

    # Rule 1 — too long since first sighting, regardless of who is scanning.
    if now - first_scan_at >= FIRST_SCAN_MAX_AGE:
        days_ago = (now - first_scan_at).days
        return (
            "suspicious",
            f"first scanned {days_ago} days ago",
            first_scan_at,
            prior_event.created_at,
            prior_event.user_id,
        )

    # Rule 2 — a different user scanned it, long enough ago to be a clone
    # rather than the same bottle being re-checked.
    time_since_prior = now - prior_event.created_at
    if prior_event.user_id != current_user_id and time_since_prior >= OTHER_USER_MIN_GAP:
        hours_ago = int(time_since_prior.total_seconds() // 3600)
        return (
            "suspicious",
            f"originally scanned by another user {hours_ago}h ago",
            first_scan_at,
            prior_event.created_at,
            prior_event.user_id,
        )

    # Rule 3 — everything else is fine.
    return "verified", None, first_scan_at, prior_event.created_at, prior_event.user_id