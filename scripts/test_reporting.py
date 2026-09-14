# scripts/test_reporting.py
"""
End-to-end test of the manufacturer dashboard API.

Requires the API running:  uvicorn main:app --reload

    MFR_EMAIL=ops@kwal.co.ke MFR_PASSWORD='...' python scripts/test_reporting.py

Checks the tiering rules hold, not just that endpoints respond:
  - consumer tokens are refused
  - only own brands appear in own reporting
  - no competitor is named in the industry benchmark
  - the CSV export contains no consumer identifiers

A failing endpoint reports its status and error rather than aborting the run.
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from products.models import Manufacturer, Product  # noqa: E402

API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")
EMAIL = os.getenv("MFR_EMAIL")
PASSWORD = os.getenv("MFR_PASSWORD")
DAYS = int(os.getenv("DAYS", "90"))


def request(method: str, path: str, payload=None, token=None, raw=False):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read()
            if raw:
                return response.status, body.decode()
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:200]
    except urllib.error.URLError as exc:
        print(f"\nCannot reach {API_BASE} — is the server running?\n{exc.reason}")
        raise SystemExit(1)


def body_or_error(status: int, body) -> tuple[dict, str]:
    """
    Normalise a response into (dict, error_detail).

    A 500 returns a string body, not JSON — without this every downstream
    .get() raises AttributeError and the run dies on the first bad endpoint.
    """
    if status != 200:
        snippet = body if isinstance(body, str) else json.dumps(body)
        return {}, f"HTTP {status} {snippet[:90]}"
    if not isinstance(body, dict):
        return {}, f"unexpected body type {type(body).__name__}"
    return body, ""


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL':5} {label:38} {detail}")
    return ok


def own_and_other_brands(slug: str) -> tuple[set[str], set[str]]:
    """Brand names belonging to this manufacturer, and to everyone else."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Product.brand, Manufacturer.slug).join(
                Manufacturer, Manufacturer.id == Product.manufacturer_id
            )
        ).all()
    finally:
        db.close()

    own = {b for b, s in rows if s == slug}
    other = {b for b, s in rows if s != slug} - own
    return own, other


def main() -> int:
    if not EMAIL or not PASSWORD:
        print("set MFR_EMAIL and MFR_PASSWORD, e.g.\n")
        print("  MFR_EMAIL=ops@kwal.co.ke MFR_PASSWORD='...' python scripts/test_reporting.py")
        return 2

    print(f"api  : {API_BASE}")
    print(f"user : {EMAIL}\n")

    results = []

    # --- auth ---------------------------------------------------------
    status, body = request(
        "POST", "/manufacturer/auth/login", {"email": EMAIL, "password": PASSWORD}
    )
    login_body, error = body_or_error(status, body)
    if error or "access_token" not in login_body:
        print(f"  FAIL  login  {error or 'no access_token in response'}")
        return 1

    token = login_body["access_token"]
    results.append(check("login", True, f"role={login_body['user']['role']}"))

    status, _ = request("POST", "/manufacturer/auth/login",
                        {"email": EMAIL, "password": "wrong-password"})
    results.append(check("wrong password refused", status == 401, f"HTTP {status}"))

    status, body = request("GET", "/manufacturer/me", token=token)
    me, error = body_or_error(status, body)
    slug = me.get("manufacturer", {}).get("slug")
    results.append(check("me", bool(slug), error or f"manufacturer={slug}"))

    if not slug:
        print("\ncannot continue without a manufacturer context")
        return 1

    # A consumer token must never reach the dashboard.
    email = f"crosstest+{uuid.uuid4().hex[:8]}@example.com"
    _, consumer = request("POST", "/auth/register",
                          {"email": email, "password": "testpass1234"})
    consumer_token = consumer.get("access_token") if isinstance(consumer, dict) else None

    status, _ = request("GET", "/manufacturer/summary", token=consumer_token)
    results.append(check("consumer token refused", status == 401, f"HTTP {status}"))

    status, _ = request("GET", "/manufacturer/summary")
    results.append(check("no token refused", status in (401, 403), f"HTTP {status}"))

    own, other = own_and_other_brands(slug)

    # --- reporting ----------------------------------------------------
    status, body = request("GET", f"/manufacturer/summary?days={DAYS}", token=token)
    summary, error = body_or_error(status, body)
    totals = summary.get("totals", {})
    exposure = summary.get("exposure", {})
    results.append(
        check(
            "summary",
            not error and totals.get("scans", 0) > 0,
            error
            or f"{totals.get('scans', 0)} scans, "
               f"{summary.get('suspicious_rate', 0):.1%} suspicious",
        )
    )
    results.append(
        check(
            "value at risk",
            not error and exposure.get("detected_value_at_risk", 0) > 0,
            error
            or f"{exposure.get('currency', '?')} "
               f"{exposure.get('detected_value_at_risk', 0):,.0f} "
               f"({exposure.get('priced_coverage', 0):.0%} priced)",
        )
    )

    status, body = request("GET", f"/manufacturer/timeline?days={DAYS}", token=token)
    timeline, error = body_or_error(status, body)
    points = timeline.get("points", [])
    results.append(check("timeline", bool(points), error or f"{len(points)} days"))

    status, body = request("GET", f"/manufacturer/brands?days={DAYS}", token=token)
    brands_body, error = body_or_error(status, body)
    reported = {b["brand"] for b in brands_body.get("brands", [])}
    leaked = reported & other
    results.append(check("brands", bool(reported), error or f"{len(reported)} brands"))
    results.append(
        check("brands are own only", not leaked, f"leaked: {sorted(leaked)}" if leaked else "")
    )

    status, body = request("GET", f"/manufacturer/map?days={DAYS}", token=token)
    map_body, error = body_or_error(status, body)
    map_points = map_body.get("points", [])
    results.append(check("map", bool(map_points), error or f"{len(map_points)} clusters"))

    status, body = request("GET", f"/manufacturer/flagged?days={DAYS}", token=token)
    flagged, error = body_or_error(status, body)
    locations = flagged.get("locations", [])
    results.append(check("flagged locations", not error, error or f"{len(locations)} flagged"))

    status, body = request("GET", f"/manufacturer/benchmark?days={DAYS}", token=token)
    bench, error = body_or_error(status, body)
    categories = bench.get("categories", [])
    shown = [c for c in categories if not c["suppressed"]]
    results.append(
        check(
            "benchmark",
            bool(categories),
            error or f"{len(shown)}/{len(categories)} categories disclosed",
        )
    )

    # No competitor brand may appear anywhere in the benchmark payload.
    serialised = json.dumps(bench)
    named = sorted(b for b in other if b and f'"{b}"' in serialised)
    results.append(
        check("no competitor named", not named, f"found: {named}" if named else "")
    )

    # --- export -------------------------------------------------------
    status, csv_text = request("GET", f"/manufacturer/export.csv?days={DAYS}",
                               token=token, raw=True)
    if status != 200 or not isinstance(csv_text, str):
        results.append(check("csv export", False, f"HTTP {status}"))
        results.append(check("csv carries no consumer id", False, "no csv returned"))
    else:
        lines = csv_text.splitlines()
        header = lines[0] if lines else ""
        rows = max(len(lines) - 1, 0)
        results.append(check("csv export", rows > 0, f"{rows} rows"))
        results.append(
            check(
                "csv carries no consumer id",
                "user_id" not in header and "user" not in header,
                header[:60],
            )
        )

    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())