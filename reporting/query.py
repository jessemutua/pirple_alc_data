# reporting/query.py
"""
Flexible slicing over scan data.

Dimensions, measures and filters are whitelists mapped to SQL expressions.
Nothing from the request reaches SQL as text, and the manufacturer scope is
applied by the caller, never taken from the request body.
"""
from datetime import date, datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from drinks.scan_models import ScanEvent
from products.models import Product
from reporting.service import (
    REPORT_TZ,
    REPORT_ZONE,
    SUSPICIOUS,
    UNKNOWN,
    VERIFIED,
    _local,
    _rate,
    resolve_range,
)

MAX_GROUP_BY = 2
MAX_ROWS = 1000

WEEKDAY_NAMES = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}


def _isodow():
    return func.extract("isodow", _local())


def _day_type():
    return case((_isodow() >= 6, "weekend"), else_="weekday")


# name -> SQL expression. Anything not in here is rejected.
DIMENSIONS = {
    "day": lambda: func.date_trunc("day", _local()),
    "week": lambda: func.date_trunc("week", _local()),
    "month": lambda: func.date_trunc("month", _local()),
    "weekday": _isodow,
    "hour": lambda: func.extract("hour", _local()),
    "day_type": _day_type,
    "brand": lambda: ScanEvent.brand,
    "category": lambda: ScanEvent.category,
    "status": lambda: ScanEvent.combined_auth_status,
    "serial_result": lambda: ScanEvent.serial_result,
    "gtin": lambda: ScanEvent.gtin,
    "reason": lambda: ScanEvent.auth_reason,
}

# Measures always computed; the request chooses which to return.
MEASURES = (
    "scans",
    "verified",
    "suspicious",
    "unknown",
    "rate",
    "value_at_risk",
    "unique_serials",
)


class QueryFilters(BaseModel):
    brand: Optional[list[str]] = None
    category: Optional[list[str]] = None
    status: Optional[list[str]] = None
    serial_result: Optional[list[str]] = None
    gtin: Optional[list[str]] = None
    day_type: Optional[str] = None          # "weekend" | "weekday"
    hours: Optional[list[int]] = None       # [from_hour, to_hour] inclusive


class QuerySpec(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    days: Optional[int] = Field(default=None, ge=1, le=365)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    group_by: list[str] = Field(default_factory=lambda: ["day"])
    measures: list[str] = Field(default_factory=lambda: ["scans", "suspicious", "rate"])
    limit: int = Field(default=MAX_ROWS, ge=1, le=MAX_ROWS)
    order_desc: bool = True


def _label(dimension: str, value: Any) -> str:
    """Human readable form of a grouping key."""
    if value is None:
        return "unknown"

    if dimension in ("day", "week", "month"):
        return value.date().isoformat() if hasattr(value, "date") else str(value)
    if dimension == "weekday":
        return WEEKDAY_NAMES.get(int(value), str(value))
    if dimension == "hour":
        return f"{int(value):02d}:00"
    return str(value)


def _apply_filters(statement, filters: QueryFilters):
    if filters.brand:
        statement = statement.where(ScanEvent.brand.in_(filters.brand))
    if filters.category:
        statement = statement.where(ScanEvent.category.in_(filters.category))
    if filters.status:
        statement = statement.where(
            ScanEvent.combined_auth_status.in_(filters.status)
        )
    if filters.serial_result:
        statement = statement.where(
            ScanEvent.serial_result.in_(filters.serial_result)
        )
    if filters.gtin:
        statement = statement.where(ScanEvent.gtin.in_(filters.gtin))
    if filters.day_type in ("weekend", "weekday"):
        statement = statement.where(_day_type() == filters.day_type)
    if filters.hours and len(filters.hours) == 2:
        low, high = sorted(filters.hours)
        hour = func.extract("hour", _local())
        statement = statement.where(hour >= low, hour <= high)
    return statement


def run_query(db: Session, manufacturer_id: str, spec: QuerySpec) -> dict:
    group_by = [d for d in spec.group_by if d in DIMENSIONS][:MAX_GROUP_BY]
    if not group_by:
        group_by = ["day"]

    measures = [m for m in spec.measures if m in MEASURES] or ["scans"]

    # Same interpretation of a period as every preset endpoint.
    rng = resolve_range(spec.date_from, spec.date_to, spec.days)

    dimension_columns = [
        DIMENSIONS[name]().label(f"dim_{index}")
        for index, name in enumerate(group_by)
    ]

    aggregates = [
        func.count().label("scans"),
        func.sum(case((ScanEvent.combined_auth_status == VERIFIED, 1), else_=0)).label("verified"),
        func.sum(case((ScanEvent.combined_auth_status == SUSPICIOUS, 1), else_=0)).label("suspicious"),
        func.sum(case((ScanEvent.combined_auth_status == UNKNOWN, 1), else_=0)).label("unknown"),
        func.count(distinct(ScanEvent.serial)).label("unique_serials"),
        func.coalesce(
            func.sum(
                case(
                    (ScanEvent.combined_auth_status == SUSPICIOUS, Product.unit_price),
                    else_=0,
                )
            ),
            0,
        ).label("value_at_risk"),
    ]

    statement = (
        select(*dimension_columns, *aggregates)
        .outerjoin(Product, Product.gtin14 == ScanEvent.gtin)
        .where(
            ScanEvent.manufacturer_id == manufacturer_id,
            ScanEvent.created_at >= rng.start,
            ScanEvent.created_at < rng.end,
        )
    )

    statement = _apply_filters(statement, spec.filters)
    statement = statement.group_by(*dimension_columns)

    # Time dimensions read in order; everything else ranks by volume.
    if group_by[0] in ("day", "week", "month", "hour", "weekday"):
        statement = statement.order_by(dimension_columns[0])
    else:
        statement = statement.order_by(
            func.count().desc() if spec.order_desc else func.count()
        )

    rows = db.execute(statement.limit(spec.limit)).all()

    results = []
    for row in rows:
        entry: dict[str, Any] = {}

        for index, name in enumerate(group_by):
            raw = getattr(row, f"dim_{index}")
            entry[name] = _label(name, raw)

        values = {
            "scans": row.scans or 0,
            "verified": row.verified or 0,
            "suspicious": row.suspicious or 0,
            "unknown": row.unknown or 0,
            "unique_serials": row.unique_serials or 0,
            "value_at_risk": float(row.value_at_risk or 0),
            "rate": _rate(row.suspicious, row.scans),
        }

        for measure in measures:
            entry[measure] = values[measure]

        # Always present so the client can mark a slice too thin to trust.
        entry["scans"] = values["scans"]
        results.append(entry)

    return {
        "timezone": REPORT_TZ,
        "range": rng.as_dict(),
        "group_by": group_by,
        "measures": measures,
        "row_count": len(results),
        "rows": results,
    }


def facets(db: Session, manufacturer_id: str, days: int = 90) -> dict:
    """
    The values actually present in this manufacturer's data, for populating
    filter controls. Never a hardcoded list, which would show options that
    return nothing.
    """
    start = datetime.now(REPORT_ZONE) - timedelta(days=days)

    def distinct_values(column):
        return [
            value
            for value in db.scalars(
                select(distinct(column))
                .where(
                    ScanEvent.manufacturer_id == manufacturer_id,
                    ScanEvent.created_at >= start,
                    column.isnot(None),
                )
                .order_by(column)
            ).all()
        ]

    return {
        "brand": distinct_values(ScanEvent.brand),
        "category": distinct_values(ScanEvent.category),
        "status": distinct_values(ScanEvent.combined_auth_status),
        "serial_result": distinct_values(ScanEvent.serial_result),
        "dimensions": list(DIMENSIONS.keys()),
        "measures": list(MEASURES),
    }