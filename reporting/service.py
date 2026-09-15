# reporting/service.py
"""
Dashboard queries.

Two rules live here because this is the only layer that reads scan data:

  1. Own-manufacturer queries always filter on manufacturer_id.
  2. Industry queries return category aggregates only, and suppress any
     bucket thin enough to be reverse-engineered into one competitor.

Consumer user_id is never returned by anything in this module.

Timestamps are stored in UTC and grouped in local time. Kenya is UTC+3, so
grouping in UTC pushes evening scans onto the following day and makes hour
of day and day of week meaningless.
"""
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import Numeric, case, cast, distinct, func, select
from sqlalchemy.orm import Session

from drinks.scan_models import ScanEvent
from products.models import Product

# Reporting timezone. Storage stays UTC; only presentation converts.
REPORT_TZ = os.getenv("REPORT_TIMEZONE", "Africa/Nairobi")
REPORT_ZONE = ZoneInfo(REPORT_TZ)

# Below either threshold, a category aggregate is withheld, otherwise a
# manufacturer can subtract its own figures and read a competitor's.
MIN_MANUFACTURERS_PER_BUCKET = 3
MIN_SCANS_PER_BUCKET = 50

# ~110 m. Matches the accuracy the handset actually reports; a finer grid
# would imply precision the data does not have.
COORD_PRECISION = 3

DEFAULT_DAYS = 30
MAX_DAYS = 365

SUSPICIOUS = "suspicious"
VERIFIED = "verified"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class DateRange:
    """
    A reporting period, plus the equivalent period immediately before it.

    Boundaries are UTC instants; the caller supplies local calendar days.
    """

    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    days: int

    def as_dict(self) -> dict:
        return {
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "days": self.days,
            "timezone": REPORT_TZ,
        }


def resolve_range(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    days: Optional[int] = None,
) -> DateRange:
    """
    The one place a reporting period is interpreted.

    Explicit dates are local calendar days: 1 June to 30 June means Nairobi
    days, not UTC days. Without them it is a rolling window ending now.
    """
    if date_from and date_to:
        if date_to < date_from:
            date_from, date_to = date_to, date_from

        start = datetime.combine(date_from, time.min, REPORT_ZONE)
        end = datetime.combine(date_to + timedelta(days=1), time.min, REPORT_ZONE)
        span_days = (date_to - date_from).days + 1
    else:
        span_days = min(max(days or DEFAULT_DAYS, 1), MAX_DAYS)
        end = datetime.now(REPORT_ZONE)
        start = end - timedelta(days=span_days)

    span = end - start
    return DateRange(
        start=start,
        end=end,
        previous_start=start - span,
        previous_end=start,
        days=span_days,
    )


def _local(column=ScanEvent.created_at):
    """
    The timestamp as local wall clock time.

    Every grouping by day, weekday or hour must go through this, or the
    buckets are wrong by the UTC offset.
    """
    return func.timezone(REPORT_TZ, column)


def _status_counts():
    """Reusable conditional counters for the three verdicts."""
    return (
        func.count().label("scans"),
        func.sum(case((ScanEvent.combined_auth_status == VERIFIED, 1), else_=0)).label("verified"),
        func.sum(case((ScanEvent.combined_auth_status == SUSPICIOUS, 1), else_=0)).label("suspicious"),
        func.sum(case((ScanEvent.combined_auth_status == UNKNOWN, 1), else_=0)).label("unknown"),
    )


def _rate(suspicious: Optional[int], scans: Optional[int]) -> float:
    if not scans:
        return 0.0
    return round((suspicious or 0) / scans, 4)


def _in_range(start: datetime, end: datetime):
    return (ScanEvent.created_at >= start, ScanEvent.created_at < end)


def _currency(db: Session, manufacturer_id: str) -> str:
    """
    Reported currency for this manufacturer's catalogue.

    'mixed' when products disagree: adding different currencies together
    silently would be worse than reporting no figure at all.
    """
    rows = db.scalars(
        select(distinct(Product.currency)).where(
            Product.manufacturer_id == manufacturer_id
        )
    ).all()
    if len(rows) == 1:
        return rows[0]
    return "mixed" if rows else "KES"


def _exposure(db: Session, manufacturer_id: str, start: datetime, end: datetime):
    """
    Value of suspicious scans, priced at what the manufacturer sells for.

    Observed detections only, never extrapolated to market size. Every
    shilling here traces back to a specific scan.
    """
    return db.execute(
        select(
            func.coalesce(func.sum(Product.unit_price), 0).label("value"),
            func.count().label("priced_scans"),
        )
        .select_from(ScanEvent)
        .join(Product, Product.gtin14 == ScanEvent.gtin)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(start, end),
            ScanEvent.combined_auth_status == SUSPICIOUS,
            Product.unit_price.isnot(None),
        )
    ).one()


def summary(db: Session, manufacturer_id: str, rng: DateRange) -> dict:
    """Headline counts for this manufacturer, against the previous period."""
    scans, verified, suspicious, unknown = _status_counts()

    current = db.execute(
        select(scans, verified, suspicious, unknown).where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.start, rng.end),
        )
    ).one()

    prior = db.execute(
        select(scans, suspicious).where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.previous_start, rng.previous_end),
        )
    ).one()

    current_rate = _rate(current.suspicious, current.scans)
    prior_rate = _rate(prior.suspicious, prior.scans)

    exposure = _exposure(db, manufacturer_id, rng.start, rng.end)
    prior_exposure = db.execute(
        select(func.coalesce(func.sum(Product.unit_price), 0))
        .select_from(ScanEvent)
        .join(Product, Product.gtin14 == ScanEvent.gtin)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.previous_start, rng.previous_end),
            ScanEvent.combined_auth_status == SUSPICIOUS,
            Product.unit_price.isnot(None),
        )
    ).scalar()

    suspicious_count = current.suspicious or 0

    return {
        "period": rng.as_dict(),
        "totals": {
            "scans": current.scans or 0,
            "verified": current.verified or 0,
            "suspicious": suspicious_count,
            "unknown": current.unknown or 0,
        },
        "suspicious_rate": current_rate,
        "exposure": {
            "currency": _currency(db, manufacturer_id),
            # Suspicious scans x unit price. Detected, not extrapolated.
            "detected_value_at_risk": float(exposure.value or 0),
            "previous_value_at_risk": float(prior_exposure or 0),
            # Share of suspicious scans that had a price to apply. Below 1.0
            # the figure understates, and the dashboard must say so.
            "priced_coverage": round(
                (exposure.priced_scans / suspicious_count) if suspicious_count else 0.0,
                4,
            ),
        },
        "previous": {
            "scans": prior.scans or 0,
            "suspicious_rate": prior_rate,
        },
        "change": {
            "scans": (current.scans or 0) - (prior.scans or 0),
            "suspicious_rate_points": round(current_rate - prior_rate, 4),
            "value_at_risk": float((exposure.value or 0) - (prior_exposure or 0)),
        },
    }


def timeline(db: Session, manufacturer_id: str, rng: DateRange) -> list[dict]:
    """Daily verdict counts, bucketed by local calendar day."""
    day = func.date_trunc("day", _local()).label("day")
    scans, verified, suspicious, unknown = _status_counts()

    rows = db.execute(
        select(day, scans, verified, suspicious, unknown)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.start, rng.end),
        )
        .group_by(day)
        .order_by(day)
    ).all()

    return [
        {
            "date": row.day.date().isoformat(),
            "scans": row.scans,
            "verified": row.verified or 0,
            "suspicious": row.suspicious or 0,
            "unknown": row.unknown or 0,
            "suspicious_rate": _rate(row.suspicious, row.scans),
        }
        for row in rows
    ]


def brands(db: Session, manufacturer_id: str, rng: DateRange) -> list[dict]:
    """
    Per-brand breakdown: which of your own labels are being faked, and what
    that is worth at your own selling price.
    """
    scans, verified, suspicious, unknown = _status_counts()

    value_at_risk = func.coalesce(
        func.sum(
            case(
                (ScanEvent.combined_auth_status == SUSPICIOUS, Product.unit_price),
                else_=0,
            )
        ),
        0,
    ).label("value_at_risk")

    rows = db.execute(
        select(
            ScanEvent.brand,
            ScanEvent.category,
            scans,
            verified,
            suspicious,
            unknown,
            value_at_risk,
        )
        .outerjoin(Product, Product.gtin14 == ScanEvent.gtin)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.start, rng.end),
            ScanEvent.brand.isnot(None),
        )
        .group_by(ScanEvent.brand, ScanEvent.category)
        .order_by(func.count().desc())
    ).all()

    return [
        {
            "brand": row.brand,
            "category": row.category,
            "scans": row.scans,
            "verified": row.verified or 0,
            "suspicious": row.suspicious or 0,
            "unknown": row.unknown or 0,
            "suspicious_rate": _rate(row.suspicious, row.scans),
            "detected_value_at_risk": float(row.value_at_risk or 0),
        }
        for row in rows
    ]


def map_points(
    db: Session, manufacturer_id: str, rng: DateRange, min_scans: int = 1
) -> list[dict]:
    """
    Scan clusters for the heatmap.

    Coordinates only: a point on a map, never a named premises. The handset
    reports roughly 100 m accuracy, so a point is a block, not a shop.
    """
    lat = func.round(cast(ScanEvent.location_lat, Numeric), COORD_PRECISION).label("lat")
    lng = func.round(cast(ScanEvent.location_lng, Numeric), COORD_PRECISION).label("lng")
    scans, _verified, suspicious, _unknown = _status_counts()

    rows = db.execute(
        select(lat, lng, scans, suspicious)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.start, rng.end),
            ScanEvent.location_lat.isnot(None),
            ScanEvent.location_lng.isnot(None),
        )
        .group_by(lat, lng)
        .having(func.count() >= min_scans)
        .order_by(func.count().desc())
    ).all()

    return [
        {
            "lat": float(row.lat),
            "lng": float(row.lng),
            "scans": row.scans,
            "suspicious": row.suspicious or 0,
            "suspicious_rate": _rate(row.suspicious, row.scans),
        }
        for row in rows
    ]


def flagged_locations(
    db: Session, manufacturer_id: str, rng: DateRange, limit: int = 25
) -> list[dict]:
    """Clusters ranked by suspicious volume: the enforcement handoff list."""
    points = map_points(db, manufacturer_id, rng, min_scans=3)
    flagged = [p for p in points if p["suspicious"] > 0]
    flagged.sort(key=lambda p: (p["suspicious"], p["suspicious_rate"]), reverse=True)
    return flagged[:limit]


def category_benchmark(db: Session, manufacturer_id: str, rng: DateRange) -> list[dict]:
    """
    Own rate against the whole category, industry-wide.

    Category aggregates only: no competitor is ever named, and a bucket
    backed by too few manufacturers or too little volume is withheld rather
    than reported, since it could otherwise be decomposed into one rival.
    """
    scans, _verified, suspicious, _unknown = _status_counts()

    own_rows = db.execute(
        select(ScanEvent.category, scans, suspicious)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.start, rng.end),
            ScanEvent.category.isnot(None),
        )
        .group_by(ScanEvent.category)
    ).all()

    own = {row.category: row for row in own_rows}

    industry_rows = db.execute(
        select(
            ScanEvent.category,
            scans,
            suspicious,
            func.count(distinct(ScanEvent.manufacturer_id)).label("manufacturers"),
        )
        .where(
            *_in_range(rng.start, rng.end),
            ScanEvent.category.isnot(None),
            ScanEvent.manufacturer_id.isnot(None),
        )
        .group_by(ScanEvent.category)
    ).all()

    results = []
    for row in industry_rows:
        mine = own.get(row.category)
        if mine is None:
            continue  # not a category this manufacturer sells into

        suppressed = (
            row.manufacturers < MIN_MANUFACTURERS_PER_BUCKET
            or row.scans < MIN_SCANS_PER_BUCKET
        )

        results.append(
            {
                "category": row.category,
                "own": {
                    "scans": mine.scans,
                    "suspicious": mine.suspicious or 0,
                    "suspicious_rate": _rate(mine.suspicious, mine.scans),
                },
                "industry": None
                if suppressed
                else {
                    "scans": row.scans,
                    "suspicious_rate": _rate(row.suspicious, row.scans),
                    "manufacturers": row.manufacturers,
                },
                "suppressed": suppressed,
                "suppressed_reason": "not enough participants in this category"
                if suppressed
                else None,
            }
        )

    results.sort(key=lambda r: r["own"]["scans"], reverse=True)
    return results


def recent_activity(
    db: Session,
    manufacturer_id: str,
    since: Optional[datetime] = None,
    limit: int = 50,
) -> list[dict]:
    """
    The newest scans for this manufacturer, for the live window.

    `since` returns only what is newer, so a poll transfers nothing when
    nothing has happened. No consumer identifiers, as everywhere else.
    """
    statement = select(
        ScanEvent.id,
        ScanEvent.created_at,
        ScanEvent.brand,
        ScanEvent.category,
        ScanEvent.gtin,
        ScanEvent.combined_auth_status,
        ScanEvent.auth_reason,
        ScanEvent.location_lat,
        ScanEvent.location_lng,
        Product.product_name,
    ).outerjoin(Product, Product.gtin14 == ScanEvent.gtin).where(
        ScanEvent.manufacturer_id == manufacturer_id
    )

    if since is not None:
        statement = statement.where(ScanEvent.created_at > since)

    rows = db.execute(
        statement.order_by(ScanEvent.created_at.desc()).limit(limit)
    ).all()

    return [
        {
            "id": row.id,
            "scanned_at": row.created_at.astimezone(REPORT_ZONE).isoformat()
            if row.created_at
            else None,
            "brand": row.brand,
            "product": row.product_name,
            "category": row.category,
            "gtin": row.gtin,
            "status": row.combined_auth_status,
            "reason": row.auth_reason,
            "lat": row.location_lat,
            "lng": row.location_lng,
        }
        for row in rows
    ]


def export_rows(
    db: Session, manufacturer_id: str, rng: DateRange, limit: int = 50000
):
    """
    Own scans, flattened for CSV.

    No user_id, ever. Manufacturers buy counterfeit intelligence, not a
    record of who drinks what.

    Timestamps are emitted in local time with their offset, so an analyst
    reads the hour the scan actually happened.
    """
    rows = db.execute(
        select(
            ScanEvent.created_at,
            ScanEvent.gtin,
            ScanEvent.brand,
            ScanEvent.category,
            ScanEvent.serial,
            ScanEvent.registry_result,
            ScanEvent.serial_result,
            ScanEvent.combined_auth_status,
            ScanEvent.auth_reason,
            ScanEvent.location_lat,
            ScanEvent.location_lng,
            Product.unit_price,
            Product.currency,
        )
        .outerjoin(Product, Product.gtin14 == ScanEvent.gtin)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.start, rng.end),
        )
        .order_by(ScanEvent.created_at.desc())
        .limit(limit)
    ).all()

    for row in rows:
        local = row.created_at.astimezone(REPORT_ZONE) if row.created_at else None
        yield {
            "scanned_at": local.isoformat() if local else "",
            "gtin": row.gtin or "",
            "brand": row.brand or "",
            "category": row.category or "",
            "serial": row.serial or "",
            "registry_result": row.registry_result or "",
            "serial_result": row.serial_result or "",
            "status": row.combined_auth_status or "",
            "reason": row.auth_reason or "",
            "unit_price": float(row.unit_price) if row.unit_price is not None else "",
            "currency": row.currency or "",
            "lat": row.location_lat if row.location_lat is not None else "",
            "lng": row.location_lng if row.location_lng is not None else "",
        }

def counties(db: Session, manufacturer_id: str, rng: DateRange) -> dict:
    """
    Per-county totals for the national map.

    Counties with no scans are absent rather than zero, so the map can render
    them as "no data" instead of as a result. Scans with no county are
    reported separately rather than silently dropped.
    """
    scans, verified, suspicious, unknown = _status_counts()

    value_at_risk = func.coalesce(
        func.sum(
            case(
                (ScanEvent.combined_auth_status == SUSPICIOUS, Product.unit_price),
                else_=0,
            )
        ),
        0,
    ).label("value_at_risk")

    rows = db.execute(
        select(
            ScanEvent.county,
            scans,
            verified,
            suspicious,
            unknown,
            value_at_risk,
        )
        .outerjoin(Product, Product.gtin14 == ScanEvent.gtin)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.start, rng.end),
            ScanEvent.county.isnot(None),
        )
        .group_by(ScanEvent.county)
        .order_by(func.count().desc())
    ).all()

    untagged = db.scalar(
        select(func.count())
        .select_from(ScanEvent)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            *_in_range(rng.start, rng.end),
            ScanEvent.county.is_(None),
        )
    )

    results = [
        {
            "county": row.county,
            "scans": row.scans,
            "verified": row.verified or 0,
            "suspicious": row.suspicious or 0,
            "unknown": row.unknown or 0,
            "suspicious_rate": _rate(row.suspicious, row.scans),
            "detected_value_at_risk": float(row.value_at_risk or 0),
        }
        for row in rows
    ]

    return {
        "counties": results,
        # Scans with no county: no coordinates, or a point outside every
        # boundary. Shown so coverage is never overstated.
        "untagged_scans": untagged or 0,
        "max_suspicious": max((r["suspicious"] for r in results), default=0),
        "max_scans": max((r["scans"] for r in results), default=0),
    }