# verification/engine.py
"""
Is this seal the one the manufacturer issued, and is it still the only one?

The code is printed on the tamper seal, so a scannable code means an
unopened bottle. That is the whole basis of what follows.

Four outcomes, and three of them are certain:

    not issued          the code is not in the manufacturer's ledger
    retired             somebody opened that bottle, so this seal is new
    in two places       one code, two bottles
    valid               a manufacturer-issued seal, not yet opened

"Valid" is deliberately not "genuine". A seal code proves the manufacturer
issued that code. It says nothing about the liquid, and the wording must
never imply otherwise.

Anything softer than certain is recorded for the manufacturer and never
shown as a verdict to the person holding the bottle. Telling somebody their
real bottle is fake is the error that costs a manufacturer trust, and at
this stage we have no data with which to justify taking that risk.
"""
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from drinks.scan_models import ScanEvent
from products.models import ProductSerial

# Stored verdicts. These strings are what reporting and the dashboard
# already understand, so they do not change.
STATUS_VALID = "verified"
STATUS_INVALID = "suspicious"
STATUS_UNKNOWN = "unknown"

# Two fixes further apart than this are different places. It is a statement
# about phone GPS in a built-up area and about the footprint of a shop, not
# a guess about how bottles behave, which is why it is the only distance in
# the system. Phones report their own accuracy and once that is stored this
# should become max(floor, reported accuracy of both fixes).
SEPARATION_M = float(os.getenv("VERIFY_SEPARATION_M", "500"))

# Scans closer together than this in place and time are one occasion. Six
# friends passing a bottle round a table must never read as six bottles.
# Used only for what the manufacturer sees, never for a consumer verdict.
SAME_PLACE_M = float(os.getenv("VERIFY_SAME_PLACE_M", "300"))
SAME_OCCASION_HOURS = float(os.getenv("VERIFY_SAME_OCCASION_HOURS", "10"))

EARTH_RADIUS_M = 6371000.0


@dataclass(frozen=True)
class ScanContext:
    """The scan being judged. Coordinates may be absent."""
    gtin14: str
    serial: str
    user_id: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    at: Optional[datetime] = None

    def moment(self) -> datetime:
        return _as_utc(self.at) if self.at else datetime.now(timezone.utc)


@dataclass
class Verdict:
    status: str
    reason: Optional[str] = None

    # Plain facts about the bottle, shown alongside a valid result so the
    # person can square it with what they know. Never an accusation.
    facts: Dict[str, Any] = field(default_factory=dict)

    # For the manufacturer only. Computed on every scan whether or not
    # anything reads it today, because without it there is nothing to learn
    # from later.
    features: Dict[str, Any] = field(default_factory=dict)

    first_scan_at: Optional[datetime] = None
    prior_scan_at: Optional[datetime] = None
    prior_scan_user_id: Optional[str] = None


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _distance_m(
    lat1: Optional[float],
    lng1: Optional[float],
    lat2: Optional[float],
    lng2: Optional[float],
) -> Optional[float]:
    """Great-circle distance in metres, or None when either point is missing."""
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return None

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _hours_between(later: datetime, earlier: datetime) -> float:
    return (later - _as_utc(earlier)).total_seconds() / 3600.0


def _elsewhere(
    ctx: ScanContext, history: List[ScanEvent]
) -> Optional[Tuple[ScanEvent, float]]:
    """
    The earliest scan by somebody else that is too far from here to be the
    same bottle sitting still.

    Same account is exempt. A buyer scanning in the shop and again at home
    is the most ordinary thing that will ever happen to this app.
    """
    if ctx.lat is None or ctx.lng is None:
        return None

    for event in history:
        if event.user_id == ctx.user_id:
            continue

        distance = _distance_m(ctx.lat, ctx.lng, event.location_lat, event.location_lng)
        if distance is not None and distance > SEPARATION_M:
            return event, distance

    return None


def _occasions(history: List[ScanEvent], ctx: ScanContext) -> List[Dict[str, Any]]:
    """
    Collapse the history plus this scan into the occasions the bottle
    surfaced on. Scans close in place and time are one occasion however
    many people took part.
    """
    rows: List[Tuple[datetime, Optional[float], Optional[float], str]] = [
        (_as_utc(e.created_at), e.location_lat, e.location_lng, e.user_id)
        for e in history
    ]
    rows.append((ctx.moment(), ctx.lat, ctx.lng, ctx.user_id))
    rows.sort(key=lambda row: row[0])

    out: List[Dict[str, Any]] = []
    for at, lat, lng, user_id in rows:
        joined = False
        if out:
            last = out[-1]
            within_time = _hours_between(at, last["ended_at"]) <= SAME_OCCASION_HOURS
            distance = _distance_m(last["lat"], last["lng"], lat, lng)
            within_place = distance is None or distance <= SAME_PLACE_M
            if within_time and within_place:
                last["ended_at"] = at
                last["scans"] += 1
                last["users"].add(user_id)
                if last["lat"] is None:
                    last["lat"], last["lng"] = lat, lng
                joined = True

        if not joined:
            out.append(
                {
                    "started_at": at,
                    "ended_at": at,
                    "lat": lat,
                    "lng": lng,
                    "scans": 1,
                    "users": {user_id},
                }
            )
    return out


def _features(
    ctx: ScanContext, history: List[ScanEvent], occasions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Everything the next version will need, captured whether or not anything
    reads it today. Nothing here reaches the consumer.
    """
    first = history[0] if history else None
    now = ctx.moment()

    accounts: Set[str] = {e.user_id for e in history} | {ctx.user_id}
    largest = max((len(o["users"]) for o in occasions), default=1)

    distance_from_first = (
        _distance_m(ctx.lat, ctx.lng, first.location_lat, first.location_lng)
        if first
        else None
    )

    return {
        "scans_before": len(history),
        "distinct_accounts": len(accounts),
        "occasions": len(occasions),
        "largest_occasion_people": largest,
        "hours_since_first_scan": (
            round(_hours_between(now, first.created_at), 2) if first else 0.0
        ),
        "metres_from_first_scan": (
            round(distance_from_first) if distance_from_first is not None else None
        ),
        "had_location": ctx.lat is not None and ctx.lng is not None,
    }


def evaluate(db: Session, ctx: ScanContext) -> Verdict:
    """
    Judge one scan of a code already known to have been issued.

    Scoped to (gtin, serial): GS1 guarantees a serial is unique only WITHIN
    a product, so two manufacturers may legitimately issue the same string.
    """
    history: List[ScanEvent] = (
        db.query(ScanEvent)
        .filter(ScanEvent.serial == ctx.serial)
        .filter(ScanEvent.gtin == ctx.gtin14)
        .order_by(ScanEvent.created_at.asc())
        .all()
    )

    occasions = _occasions(history, ctx)
    features = _features(ctx, history, occasions)

    first = history[0] if history else None
    prior = history[-1] if history else None

    facts: Dict[str, Any] = {
        "times_seen": len(history) + 1,
        "first_seen_at": _as_utc(first.created_at).isoformat() if first else None,
        "first_seen_county": first.county if first else None,
    }

    def built(status: str, reason: Optional[str] = None) -> Verdict:
        return Verdict(
            status=status,
            reason=reason,
            facts=facts,
            features=features,
            first_scan_at=_as_utc(first.created_at) if first else ctx.moment(),
            prior_scan_at=_as_utc(prior.created_at) if prior else None,
            prior_scan_user_id=prior.user_id if prior else None,
        )

    # Retired. Somebody opened that bottle, so the seal in front of this
    # person is a different one. Certain, given a real retirement.
    row = db.get(ProductSerial, (ctx.gtin14, ctx.serial))
    if row is not None and getattr(row, "retired_at", None) is not None:
        when = _as_utc(row.retired_at).date().isoformat()
        facts["retired_at"] = _as_utc(row.retired_at).isoformat()
        return built(
            STATUS_INVALID,
            f"this bottle was opened on {when}, so this seal is not the original one",
        )

    # One code, two places. Same account is exempt.
    found = _elsewhere(ctx, history)
    if found:
        event, distance = found
        when = _as_utc(event.created_at).date().isoformat()
        km = distance / 1000.0
        where = f"{km:.0f} km" if km >= 1 else f"{int(distance)} m"
        return built(
            STATUS_INVALID,
            f"this code was scanned {where} away on {when}, "
            f"so it is on more than one bottle",
        )

    # Nothing contradicts it. Which is not the same as vouching for it.
    return built(STATUS_VALID)