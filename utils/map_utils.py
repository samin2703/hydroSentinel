from __future__ import annotations

from math import asin, cos, radians, sin, sqrt


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometers."""
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    c = 2 * asin(sqrt(a))
    return r * c


def _dms_to_decimal(dms: tuple, ref: str | None) -> float | None:
    """Convert EXIF DMS tuples to signed decimal degrees."""
    if not dms or len(dms) != 3:
        return None

    try:
        deg = float(dms[0][0]) / float(dms[0][1])
        mins = float(dms[1][0]) / float(dms[1][1])
        secs = float(dms[2][0]) / float(dms[2][1])
    except (TypeError, ZeroDivisionError, IndexError):
        return None

    value = deg + (mins / 60.0) + (secs / 3600.0)
    if ref in {"S", "W"}:
        value = -value
    return value


def extract_gps_from_exif(image) -> tuple[float, float] | None:
    """Extract GPS coordinates from a PIL image's EXIF metadata if present."""
    try:
        exif = image.getexif()
    except Exception:
        return None

    if not exif:
        return None

    gps_ifd = exif.get_ifd(34853)
    if not gps_ifd:
        return None

    lat_dms = gps_ifd.get(2)
    lat_ref = gps_ifd.get(1)
    lon_dms = gps_ifd.get(4)
    lon_ref = gps_ifd.get(3)

    lat = _dms_to_decimal(lat_dms, lat_ref)
    lon = _dms_to_decimal(lon_dms, lon_ref)

    if lat is None or lon is None:
        return None

    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
        return (lat, lon)

    return None


def _compute_location_factor(
    drainage_vulnerability: float,
    flood_history: float,
    lowland_exposure: float,
    canal_river_proximity: float,
) -> float:
    """
    Compute a 0-1 location vulnerability factor.

    Inputs are 0-1 vulnerability scores where higher means more flood-prone.
    """
    score = (
        (drainage_vulnerability * 0.40)
        + (flood_history * 0.30)
        + (lowland_exposure * 0.20)
        + (canal_river_proximity * 0.10)
    )
    return round(max(0.0, min(1.0, score)), 2)


_LOCATION_DATA = {
    "Mirpur": {
        "center_lat": 23.8103,
        "center_lon": 90.3667,
        "zone_type": "High-density residential",
        "drain_capacity": "Medium-Low",
        "flood_history": "High",
        "terrain": "Mostly low-lying pockets",
        "nearby_water_body": "Turag basin influence",
        "location_factor": _compute_location_factor(
            drainage_vulnerability=0.70,
            flood_history=0.80,
            lowland_exposure=0.65,
            canal_river_proximity=0.55,
        ),
    },
    "Mohammadpur": {
        "center_lat": 23.7660,
        "center_lon": 90.3580,
        "zone_type": "Mixed residential-commercial",
        "drain_capacity": "Medium-Low",
        "flood_history": "Moderate-High",
        "terrain": "Flat urban",
        "nearby_water_body": "Canal-linked drainage",
        "location_factor": _compute_location_factor(
            drainage_vulnerability=0.65,
            flood_history=0.70,
            lowland_exposure=0.50,
            canal_river_proximity=0.60,
        ),
    },
    "Dhanmondi": {
        "center_lat": 23.7465,
        "center_lon": 90.3760,
        "zone_type": "Planned residential-commercial",
        "drain_capacity": "Medium",
        "flood_history": "Moderate",
        "terrain": "Relatively flat",
        "nearby_water_body": "Dhanmondi Lake",
        "location_factor": _compute_location_factor(
            drainage_vulnerability=0.55,
            flood_history=0.50,
            lowland_exposure=0.45,
            canal_river_proximity=0.40,
        ),
    },
    "Old Dhaka": {
        "center_lat": 23.7115,
        "center_lon": 90.4072,
        "zone_type": "Historic dense urban",
        "drain_capacity": "Low",
        "flood_history": "High",
        "terrain": "Low-lying historic core",
        "nearby_water_body": "Buriganga influence",
        "location_factor": _compute_location_factor(
            drainage_vulnerability=0.80,
            flood_history=0.85,
            lowland_exposure=0.75,
            canal_river_proximity=0.70,
        ),
    },
    "Badda": {
        "center_lat": 23.7806,
        "center_lon": 90.4255,
        "zone_type": "Rapid-growth mixed urban",
        "drain_capacity": "Low",
        "flood_history": "High",
        "terrain": "Low-lying wetlands fringe",
        "nearby_water_body": "Balu river corridor",
        "location_factor": _compute_location_factor(
            drainage_vulnerability=0.85,
            flood_history=0.80,
            lowland_exposure=0.85,
            canal_river_proximity=0.75,
        ),
    },
    "Jatrabari": {
        "center_lat": 23.7104,
        "center_lon": 90.4340,
        "zone_type": "Transport-heavy urban",
        "drain_capacity": "Low",
        "flood_history": "High",
        "terrain": "Low and congestion-prone",
        "nearby_water_body": "Shitalakkhya-Buriganga network",
        "location_factor": _compute_location_factor(
            drainage_vulnerability=0.80,
            flood_history=0.80,
            lowland_exposure=0.70,
            canal_river_proximity=0.60,
        ),
    },
    "Uttara": {
        "center_lat": 23.8740,
        "center_lon": 90.4003,
        "zone_type": "Planned residential",
        "drain_capacity": "Medium-High",
        "flood_history": "Low-Moderate",
        "terrain": "Relatively elevated sections",
        "nearby_water_body": "Turag proximity",
        "location_factor": _compute_location_factor(
            drainage_vulnerability=0.35,
            flood_history=0.30,
            lowland_exposure=0.35,
            canal_river_proximity=0.45,
        ),
    },
    "Khilgaon": {
        "center_lat": 23.7511,
        "center_lon": 90.4268,
        "zone_type": "Mixed residential",
        "drain_capacity": "Medium-Low",
        "flood_history": "Moderate",
        "terrain": "Flat urban",
        "nearby_water_body": "Local canal links",
        "location_factor": _compute_location_factor(
            drainage_vulnerability=0.60,
            flood_history=0.55,
            lowland_exposure=0.50,
            canal_river_proximity=0.50,
        ),
    },
    "Bashundhara": {
        "center_lat": 23.8193,
        "center_lon": 90.4348,
        "zone_type": "Planned residential-commercial",
        "drain_capacity": "Medium",
        "flood_history": "Moderate",
        "terrain": "Partly reclaimed lowland",
        "nearby_water_body": "Balu watershed influence",
        "location_factor": _compute_location_factor(
            drainage_vulnerability=0.50,
            flood_history=0.45,
            lowland_exposure=0.60,
            canal_river_proximity=0.55,
        ),
    },
}


_RIVER_CANAL_POINTS = [
    {"name": "Buriganga", "lat": 23.7040, "lon": 90.3940},
    {"name": "Turag", "lat": 23.8460, "lon": 90.3460},
    {"name": "Balu", "lat": 23.8200, "lon": 90.4550},
    {"name": "Dhanmondi Lake", "lat": 23.7440, "lon": 90.3720},
]

_WATERLOGGING_HOTSPOTS = [
    {"name": "Shantinagar", "lat": 23.7369, "lon": 90.4160},
    {"name": "Moghbazar", "lat": 23.7467, "lon": 90.4030},
    {"name": "Jatrabari", "lat": 23.7104, "lon": 90.4340},
    {"name": "Mirpur-10", "lat": 23.8060, "lon": 90.3680},
    {"name": "Badda", "lat": 23.7806, "lon": 90.4255},
]

_LOW_LYING_POINTS = [
    {"name": "Rampura fringe", "lat": 23.7630, "lon": 90.4230},
    {"name": "Banasree edge", "lat": 23.7640, "lon": 90.4380},
    {"name": "Demra belt", "lat": 23.7210, "lon": 90.4900},
    {"name": "Keraniganj lowland", "lat": 23.6900, "lon": 90.3460},
]


def _nearest_point(lat: float, lon: float, points: list[dict]) -> tuple[str, float]:
    nearest = min(
        points,
        key=lambda p: _haversine_km(lat, lon, p["lat"], p["lon"]),
    )
    distance_km = _haversine_km(lat, lon, nearest["lat"], nearest["lon"])
    return nearest["name"], distance_km


def _distance_to_vulnerability(distance_km: float, max_km: float) -> float:
    """Distance-to-risk conversion where nearby points imply higher vulnerability."""
    norm = min(max(distance_km / max_km, 0.0), 1.0)
    return 1.0 - norm


def get_area_center(location_name: str) -> tuple[float, float]:
    meta = get_location_meta(location_name)
    return float(meta.get("center_lat", 23.8103)), float(meta.get("center_lon", 90.4125))


def get_nearest_area(lat: float, lon: float) -> tuple[str, dict, float]:
    best_name = "Unknown"
    best_distance = float("inf")
    best_meta = {}

    for name, meta in _LOCATION_DATA.items():
        d = _haversine_km(lat, lon, float(meta["center_lat"]), float(meta["center_lon"]))
        if d < best_distance:
            best_distance = d
            best_name = name
            best_meta = meta

    return best_name, best_meta, best_distance


def derive_geo_factors(lat: float, lon: float) -> dict:
    """
    Derive flood vulnerability from exact coordinates in Dhaka context.

    Returns a normalized location_factor plus interpretable distance features.
    """
    nearest_river_name, dist_river = _nearest_point(lat, lon, _RIVER_CANAL_POINTS)
    nearest_hotspot_name, dist_hotspot = _nearest_point(lat, lon, _WATERLOGGING_HOTSPOTS)
    nearest_lowland_name, dist_lowland = _nearest_point(lat, lon, _LOW_LYING_POINTS)

    river_vuln = _distance_to_vulnerability(dist_river, max_km=8.0)
    hotspot_vuln = _distance_to_vulnerability(dist_hotspot, max_km=6.0)
    lowland_vuln = _distance_to_vulnerability(dist_lowland, max_km=7.0)

    # Keep a modest fixed drainage baseline for geo-only inference.
    drainage_vulnerability = 0.60

    location_factor = _compute_location_factor(
        drainage_vulnerability=drainage_vulnerability,
        flood_history=hotspot_vuln,
        lowland_exposure=lowland_vuln,
        canal_river_proximity=river_vuln,
    )

    return {
        "lat": lat,
        "lon": lon,
        "location_factor": location_factor,
        "nearest_river_or_canal": nearest_river_name,
        "distance_to_river_or_canal_km": round(dist_river, 2),
        "nearest_hotspot": nearest_hotspot_name,
        "distance_to_hotspot_km": round(dist_hotspot, 2),
        "nearest_lowland": nearest_lowland_name,
        "distance_to_lowland_km": round(dist_lowland, 2),
        "river_vulnerability": round(river_vuln, 2),
        "hotspot_vulnerability": round(hotspot_vuln, 2),
        "lowland_vulnerability": round(lowland_vuln, 2),
    }


def get_location_options() -> list[str]:
    return list(_LOCATION_DATA.keys())


def get_location_meta(location_name: str) -> dict:
    return _LOCATION_DATA.get(
        location_name,
        {
            "center_lat": 23.8103,
            "center_lon": 90.4125,
            "zone_type": "Unknown",
            "drain_capacity": "Unknown",
            "flood_history": "Unknown",
            "terrain": "Unknown",
            "nearby_water_body": "Unknown",
            "location_factor": 0.50,
        },
    )