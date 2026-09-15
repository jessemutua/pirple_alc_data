# core/geo.py
"""
Point to county resolution from a GeoJSON boundary file.

No geometry dependency: a bounding box prefilter followed by ray casting is
ample for 47 polygons, and it keeps the deployment free of native libraries.

The file is optional. Without it county_for() returns None and scanning
carries on untagged, so a missing boundary file is never an outage.
"""
import json
import os
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

BOUNDARIES_PATH = Path(
    os.getenv("COUNTY_BOUNDARIES_PATH", REPO_ROOT / "data" / "kenya_counties.geojson")
)

# GeoJSON sources disagree about property names, so try the common ones.
NAME_KEYS = (
    "COUNTY_NAM",
    "COUNTY_NAME",
    "county",
    "County",
    "shapeName",
    "NAME_1",
    "NAME",
    "name",
    "ADM1_EN",
)

# (name, min_lng, min_lat, max_lng, max_lat, [polygon, ...])
# where polygon is [exterior_ring, hole_ring, ...] and a ring is [(lng, lat)]
_regions: Optional[list[tuple]] = None
_load_attempted = False


def _name_of(properties: dict) -> Optional[str]:
    for key in NAME_KEYS:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _rings_of(geometry: dict) -> list[list[list[tuple[float, float]]]]:
    """Normalise Polygon and MultiPolygon into a list of polygons."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []

    if kind == "Polygon":
        return [coordinates]
    if kind == "MultiPolygon":
        return list(coordinates)
    return []


def _bounds(polygons) -> tuple[float, float, float, float]:
    lngs = []
    lats = []
    for polygon in polygons:
        for lng, lat in polygon[0]:
            lngs.append(lng)
            lats.append(lat)
    return min(lngs), min(lats), max(lngs), max(lats)


def _load() -> list[tuple]:
    """Parse the boundary file once. A missing file is not an error."""
    global _regions, _load_attempted

    if _regions is not None:
        return _regions
    if _load_attempted:
        return []

    _load_attempted = True

    if not BOUNDARIES_PATH.is_file():
        print(f"[geo] no boundary file at {BOUNDARIES_PATH}, counties will be untagged")
        _regions = []
        return _regions

    try:
        data = json.loads(BOUNDARIES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[geo] could not read {BOUNDARIES_PATH}: {exc}")
        _regions = []
        return _regions

    regions = []
    for feature in data.get("features", []):
        name = _name_of(feature.get("properties") or {})
        polygons = _rings_of(feature.get("geometry") or {})
        if not name or not polygons:
            continue

        try:
            min_lng, min_lat, max_lng, max_lat = _bounds(polygons)
        except (ValueError, TypeError, IndexError):
            continue

        regions.append((name, min_lng, min_lat, max_lng, max_lat, polygons))

    print(f"[geo] loaded {len(regions)} regions from {BOUNDARIES_PATH.name}")
    _regions = regions
    return _regions


def _in_ring(lng: float, lat: float, ring) -> bool:
    """Ray casting: count crossings of a horizontal ray to the right."""
    inside = False
    count = len(ring)

    j = count - 1
    for i in range(count):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]

        if (yi > lat) != (yj > lat):
            x_at_lat = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lng < x_at_lat:
                inside = not inside
        j = i

    return inside


def _in_polygon(lng: float, lat: float, polygon) -> bool:
    """Inside the exterior ring and outside every hole."""
    if not polygon or not _in_ring(lng, lat, polygon[0]):
        return False
    return not any(_in_ring(lng, lat, hole) for hole in polygon[1:])


def county_for(lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    """
    The county containing this point, or None.

    None means one of: no coordinates, no boundary file, or a point outside
    every boundary. All three are normal and none of them are errors.
    """
    if lat is None or lng is None:
        return None

    for name, min_lng, min_lat, max_lng, max_lat, polygons in _load():
        # Cheap rejection first: most regions fail this.
        if not (min_lng <= lng <= max_lng and min_lat <= lat <= max_lat):
            continue
        if any(_in_polygon(lng, lat, polygon) for polygon in polygons):
            return name

    return None


def boundaries_geojson() -> Optional[dict]:
    """
    The raw boundary file, for the dashboard to draw.

    Served from the backend rather than duplicated into the frontend, so
    tagging and drawing can never drift apart.
    """
    if not BOUNDARIES_PATH.is_file():
        return None
    try:
        return json.loads(BOUNDARIES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None