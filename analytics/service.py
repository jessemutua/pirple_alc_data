from collections import defaultdict
from statistics import mean


def build_analytics(logs, days: int) -> dict:
    if not logs:
        return {
            "meta": {
                "requestedDays": days,
                "availableDays": 0,
                "from": None,
                "to": None,
            },
            "summary": {
                "daysTracked": 0,
                "drinkingDays": 0,
                "soberDays": 0,
            },
            "trend": {
                "daily": [],
                "rollingAvg": [],
                "stats": {},
            },
            "timePattern": {},
            "drinkTypes": {},
        }

    dates = sorted({log.date for log in logs})
    available_days = len(dates)

    drinking_days = sum(1 for l in logs if l.drank)
    sober_days = available_days - drinking_days

    daily = []
    rolling = []
    window = []

    for log in logs:
        count = log.drink_count or 0

        daily.append({
            "date": log.date,
            "drank": log.drank,
            "count": count,
        })

        window.append(count)
        if len(window) > 7:
            window.pop(0)

        rolling.append({
            "date": log.date,
            "value": round(mean(window), 2),
        })

    stats = {
        "avgPerDay": round(mean([d["count"] for d in daily]), 2),
        "avgPerDrinkingDay": round(
            mean([d["count"] for d in daily if d["count"] > 0]), 2
        ) if drinking_days else 0,
        "max": max(d["count"] for d in daily),
    }

    time_pattern = defaultdict(int)
    drink_types = defaultdict(int)

    for log in logs:
        if log.drank and log.time_windows:
            for t in log.time_windows:
                time_pattern[t.lower().replace(" ", "")] += 1

        if log.drank and log.drinks:
            for k, v in log.drinks.items():
                drink_types[k.lower()] += v

    return {
        "meta": {
            "requestedDays": days,
            "availableDays": available_days,
            "from": dates[0],
            "to": dates[-1],
        },
        "summary": {
            "daysTracked": available_days,
            "drinkingDays": drinking_days,
            "soberDays": sober_days,
        },
        "trend": {
            "daily": daily,
            "rollingAvg": rolling,
            "stats": stats,
        },
        "timePattern": dict(time_pattern),
        "drinkTypes": dict(drink_types),
    }
