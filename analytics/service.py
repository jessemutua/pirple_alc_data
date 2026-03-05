# analytics/service.py
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type, datetime, timedelta
from statistics import mean
from typing import Dict, Iterable, List, Any


def _date_range(from_date: date_type, to_date: date_type) -> List[date_type]:
    if to_date < from_date:
        return []
    out: List[date_type] = []
    cur = from_date
    while cur <= to_date:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _is_weekend(d: date_type) -> bool:
    # Monday=0 ... Sunday=6
    return d.weekday() >= 5


def build_user_analytics(
    *,
    sessions: List[Any],
    from_date: date_type,
    to_date: date_type,
    requested_days: int,
) -> dict:
    """
    Build user-facing analytics from canonical session + item data.

    Expected session shape:
      session.log_date: date
      session.time_window: str
      session.items: iterable of items with:
          item.drink_type: str
          item.quantity: int
    """

    days_list = _date_range(from_date, to_date)

    # Initialize per-day aggregates (include zero-days too)
    session_count_by_day: Dict[date_type, int] = {d: 0 for d in days_list}
    qty_by_day: Dict[date_type, int] = {d: 0 for d in days_list}

    # Global aggregates
    time_pattern = defaultdict(int)  # sessions by time_window
    drink_types = defaultdict(int)   # quantities by drink_type

    # Weekend/weekday aggregates
    weekend = {"drinkingDays": 0, "sessionCount": 0, "totalQuantity": 0}
    weekday = {"drinkingDays": 0, "sessionCount": 0, "totalQuantity": 0}

    # Aggregate from sessions/items
    for s in sessions:
        d = s.log_date
        if d not in session_count_by_day:
            # Safety in case caller passed sessions slightly outside range
            continue

        session_count_by_day[d] += 1

        # time window pattern counts sessions (not days)
        if getattr(s, "time_window", None):
            tw = str(s.time_window).strip().lower().replace(" ", "_")
            time_pattern[tw] += 1

        # item quantities
        for it in (getattr(s, "items", None) or []):
            qty = getattr(it, "quantity", None)
            if qty is None:
                continue
            try:
                qty_int = int(qty)
            except Exception:
                continue
            if qty_int < 0:
                continue

            qty_by_day[d] += qty_int

            dt = str(getattr(it, "drink_type", "other")).strip().lower()
            drink_types[dt] += qty_int

    # Build daily + rolling
    daily = []
    rolling = []
    window = []

    drinking_days = 0
    total_sessions = 0
    total_quantity = 0

    max_daily_quantity = 0
    max_daily_sessions = 0

    for d in days_list:
        day_sessions = session_count_by_day[d]
        day_qty = qty_by_day[d]
        has_drinking = (day_sessions > 0) or (day_qty > 0)

        if has_drinking:
            drinking_days += 1

        total_sessions += day_sessions
        total_quantity += day_qty

        if day_qty > max_daily_quantity:
            max_daily_quantity = day_qty
        if day_sessions > max_daily_sessions:
            max_daily_sessions = day_sessions

        daily.append(
            {
                "date": d.isoformat(),
                "hasDrinking": has_drinking,
                "totalQuantity": day_qty,
                "sessionCount": day_sessions,
            }
        )

        window.append(day_qty)
        if len(window) > 7:
            window.pop(0)

        rolling.append(
            {
                "date": d.isoformat(),
                "value": round(mean(window), 2) if window else 0,
            }
        )

    days_tracked = len(days_list)
    sober_days = days_tracked - drinking_days

    avg_qty_per_day = (total_quantity / days_tracked) if days_tracked else 0
    avg_qty_per_drinking_day = (total_quantity / drinking_days) if drinking_days else 0
    avg_sessions_per_drinking_day = (total_sessions / drinking_days) if drinking_days else 0

    # Weekend vs weekday derived from per-day aggregates
    for d in days_list:
        bucket = weekend if _is_weekend(d) else weekday
        bucket["sessionCount"] += session_count_by_day[d]
        bucket["totalQuantity"] += qty_by_day[d]
        if (session_count_by_day[d] > 0) or (qty_by_day[d] > 0):
            bucket["drinkingDays"] += 1

    # Ensure all expected keys exist in timePattern/drinkTypes
    for k in ["morning", "afternoon", "evening", "night", "late_night"]:
        time_pattern.setdefault(k, 0)

    for k in ["beer", "wine", "spirits", "other"]:
        drink_types.setdefault(k, 0)

    return {
        "meta": {
            "requestedDays": requested_days,
            "availableDays": days_tracked,
            "from": from_date.isoformat() if days_tracked else None,
            "to": to_date.isoformat() if days_tracked else None,
        },
        "summary": {
            "daysTracked": days_tracked,
            "drinkingDays": drinking_days,
            "soberDays": sober_days,
            "sessionCount": total_sessions,
            "totalQuantity": total_quantity,
            "avgQuantityPerDay": round(avg_qty_per_day, 2) if days_tracked else 0,
            "avgQuantityPerDrinkingDay": round(avg_qty_per_drinking_day, 2) if drinking_days else 0,
            "avgSessionsPerDrinkingDay": round(avg_sessions_per_drinking_day, 2) if drinking_days else 0,
            "maxDailyQuantity": max_daily_quantity,
            "maxDailySessions": max_daily_sessions,
        },
        "trend": {
            "daily": daily,
            "rollingAvg7dQuantity": rolling,
        },
        "timePattern": dict(time_pattern),
        "drinkTypes": dict(drink_types),
        "weekendVsWeekday": {
            "weekend": weekend,
            "weekday": weekday,
        },
    }