from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type, timedelta
from statistics import mean
from typing import Any, Dict, List, Set


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
    return d.weekday() >= 5


def build_user_analytics(
    *,
    sessions: List[Any],
    sober_dates: Set[date_type],
    from_date: date_type,
    to_date: date_type,
    requested_days: int,
) -> dict:
    days_list = _date_range(from_date, to_date)

    session_count_by_day: Dict[date_type, int] = {d: 0 for d in days_list}
    qty_by_day: Dict[date_type, int] = {d: 0 for d in days_list}

    time_pattern = defaultdict(int)
    drink_types = defaultdict(int)

    weekend = {"drinkingDays": 0, "sessionCount": 0, "totalQuantity": 0}
    weekday = {"drinkingDays": 0, "sessionCount": 0, "totalQuantity": 0}

    for s in sessions:
        d = s.log_date
        if d not in session_count_by_day:
            continue

        session_count_by_day[d] += 1

        if getattr(s, "time_window", None):
            tw = str(s.time_window).strip().lower().replace(" ", "_")
            time_pattern[tw] += 1

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

    daily = []
    rolling = []
    window = []

    drinking_days = 0
    sober_days = 0
    total_sessions = 0
    total_quantity = 0
    max_daily_quantity = 0
    max_daily_sessions = 0

    for d in days_list:
        day_sessions = session_count_by_day