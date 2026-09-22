# reporting/report_routes.py
"""
Consumer reports, as a manufacturer sees them.

A report is one person's unverified account of one bottle they scanned. It
is shown as exactly that: never as a finding about the product, never with
the reporter's identity, and only for this manufacturer's own products.
Scope comes from the token, as everywhere else in this API.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from drinks.report_models import REPORT_REASONS, BottleReport
from products.models import Product
from reporting import service
from reporting.routes import date_range
from reporting.security import ManufacturerContext, get_current_manufacturer, get_db
from reporting.service import DateRange

router = APIRouter(prefix="/manufacturer/reports", tags=["manufacturer"])

REASON_LABELS = {
    "taste_smell_wrong": "Tastes or smells wrong",
    "felt_unwell": "Felt unwell after drinking",
    "other": "Something else",
}

# Sent with every response so no screen can show a report without it.
DISCLAIMER = (
    "Unverified consumer reports. Each is one person's account of one bottle "
    "and has not been checked by Pirple."
)

# The live window never looks further back than this, whatever `since` says.
LIVE_LOOKBACK = timedelta(days=2)


def _local(moment: Optional[datetime]) -> Optional[str]:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(service.REPORT_ZONE).isoformat()


def _row(report: BottleReport, product_name: Optional[str]) -> dict:
    """What a manufacturer may see of one report. No user id, ever."""
    return {
        "id": report.id,
        "reported_at": _local(report.created_at),
        "reason": report.reason,
        "reason_label": REASON_LABELS.get(report.reason, "Something else"),
        "note": report.note,
        "brand": report.brand,
        "product": product_name,
        "gtin": report.gtin,
        "county": report.county,
        "scan_status": report.scan_status,
        "scanned_at": _local(report.scanned_at),
    }


def _with_product(db: Session, manufacturer_id: str):
    return (
        db.query(BottleReport, Product.product_name)
        .outerjoin(Product, Product.gtin14 == BottleReport.gtin)
        .filter(BottleReport.manufacturer_id == manufacturer_id)
    )


@router.get("")
def list_reports(
    rng: DateRange = Depends(date_range),
    limit: int = Query(100, ge=1, le=500),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    manufacturer_id = context.manufacturer_id

    in_range = (
        BottleReport.manufacturer_id == manufacturer_id,
        BottleReport.created_at >= rng.start,
        BottleReport.created_at < rng.end,
    )
    count = func.count(BottleReport.id)

    reason_counts = dict(
        db.query(BottleReport.reason, count)
        .filter(*in_range)
        .group_by(BottleReport.reason)
        .all()
    )

    by_county = (
        db.query(BottleReport.county, count)
        .filter(*in_range)
        .group_by(BottleReport.county)
        .order_by(count.desc())
        .limit(10)
        .all()
    )

    by_product = (
        db.query(BottleReport.gtin, BottleReport.brand, Product.product_name, count)
        .outerjoin(Product, Product.gtin14 == BottleReport.gtin)
        .filter(*in_range)
        .group_by(BottleReport.gtin, BottleReport.brand, Product.product_name)
        .order_by(count.desc())
        .limit(10)
        .all()
    )

    latest = (
        _with_product(db, manufacturer_id)
        .filter(BottleReport.created_at >= rng.start)
        .filter(BottleReport.created_at < rng.end)
        .order_by(BottleReport.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "period": rng.as_dict(),
        "disclaimer": DISCLAIMER,
        "total": sum(reason_counts.values()),
        "felt_unwell": reason_counts.get("felt_unwell", 0),
        "by_reason": [
            {"reason": r, "label": REASON_LABELS[r], "count": reason_counts.get(r, 0)}
            for r in REPORT_REASONS
        ],
        "by_county": [{"county": c, "count": n} for c, n in by_county],
        "by_product": [
            {"gtin": g, "brand": b, "product": p, "count": n}
            for g, b, p, n in by_product
        ],
        "reports": [_row(r, p) for r, p in latest],
    }


@router.get("/recent")
def recent_reports(
    since: Optional[datetime] = Query(
        None, description="Return only reports newer than this instant"
    ),
    limit: int = Query(50, ge=1, le=200),
    context: ManufacturerContext = Depends(get_current_manufacturer),
    db: Session = Depends(get_db),
):
    """
    Newest reports, for the live window. Always means now, so it ignores the
    reporting date range, exactly like /manufacturer/activity.
    """
    floor = datetime.now(timezone.utc) - LIVE_LOOKBACK
    if since is not None:
        since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        floor = max(floor, since)

    rows = (
        _with_product(db, context.manufacturer_id)
        .filter(BottleReport.created_at > floor)
        .order_by(BottleReport.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "timezone": service.REPORT_TZ,
        "server_time": datetime.now(service.REPORT_ZONE).isoformat(),
        "disclaimer": DISCLAIMER,
        "count": len(rows),
        "reports": [_row(r, p) for r, p in rows],
    }