from __future__ import annotations

import json
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from math import radians, sin, cos, sqrt, atan2


def _haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in km."""
    r = 6371.0
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return r * c


def get_osrm_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    osrm_base_url: str = "http://router.project-osrm.org",
    timeout: int = 10,
) -> dict:
    """
    Get optimal route using OSRM (Open Source Routing Machine).
    
    Returns:
    - route_coords: list of [lon, lat] waypoints
    - distance_km: total distance
    - duration_seconds: estimated travel time
    - error: error message if route failed
    """
    url = f"{osrm_base_url}/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&steps=true"
    
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        return {
            "ok": False,
            "error": f"OSRM routing failed: {str(e)}",
            "route_coords": [],
            "distance_km": 0.0,
            "duration_seconds": 0,
        }
    
    if payload.get("code") != "Ok":
        return {
            "ok": False,
            "error": f"No route found: {payload.get('message', 'Unknown error')}",
            "route_coords": [],
            "distance_km": 0.0,
            "duration_seconds": 0,
        }
    
    routes = payload.get("routes", [])
    if not routes:
        return {
            "ok": False,
            "error": "No routes returned from OSRM",
            "route_coords": [],
            "distance_km": 0.0,
            "duration_seconds": 0,
        }
    
    route = routes[0]
    geometry = route.get("geometry", {})
    coordinates = geometry.get("coordinates", [])
    distance_m = route.get("distance", 0)
    duration_s = route.get("duration", 0)
    
    return {
        "ok": True,
        "route_coords": coordinates,
        "distance_km": round(distance_m / 1000, 2),
        "duration_seconds": int(duration_s),
    }


def filter_route_by_flood_zones(
    route_coords: list[list[float]],
    flood_incidents: list[dict],
    risk_buffer_km: float = 0.5,
) -> dict:
    """
    Check if route passes through flood-affected areas.
    
    Args:
    - route_coords: [[lon, lat], [lon, lat], ...]
    - flood_incidents: [{lat, lon, risk_label}, ...]
    - risk_buffer_km: how close to a high-risk incident counts as affected
    
    Returns:
    - affected: True if route crosses high-risk zones
    - high_risk_intersections: list of incident IDs on or near the route
    - risk_zones_crossed: number of high-risk areas
    """
    high_risk_threshold = 75  # risk_score >= 75 = "High"
    affected_incidents = []
    
    for incident in flood_incidents:
        if incident.get("risk_score", 0) < high_risk_threshold:
            continue  # Only care about High risk
        
        incident_lat = incident["lat"]
        incident_lon = incident["lon"]
        incident_id = incident.get("id", "unknown")
        
        # Check distance from each route point
        min_distance_km = float("inf")
        for coord in route_coords:
            lon, lat = coord
            dist = _haversine_distance_km(lat, incident_lat, lon, incident_lon)
            min_distance_km = min(min_distance_km, dist)
        
        if min_distance_km <= risk_buffer_km:
            affected_incidents.append({
                "id": incident_id,
                "lat": incident_lat,
                "lon": incident_lon,
                "risk_score": incident["risk_score"],
                "distance_km": round(min_distance_km, 2),
            })
    
    return {
        "affected": len(affected_incidents) > 0,
        "high_risk_intersections": affected_incidents,
        "risk_zones_crossed": len(affected_incidents),
    }


def suggest_alternate_routes(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    flood_incidents: list[dict],
    osrm_base_url: str = "http://router.project-osrm.org",
) -> dict:
    """
    Get primary route and check for flood impacts. In production, could fetch
    multiple alternatives using waypoint variations.
    
    Returns:
    - primary_route: main route data
    - flooding_risk: whether primary route is affected
    - recommendation: text advice for driver
    """
    # Get primary route
    primary = get_osrm_route(
        start_lat, start_lon, end_lat, end_lon, osrm_base_url
    )
    
    if not primary.get("ok"):
        return {
            "ok": False,
            "error": primary["error"],
            "primary_route": None,
            "flooding_risk": None,
            "recommendation": "Unable to calculate routes. Check your destination.",
        }
    
    # Check if primary route crosses flood zones
    flooding_impact = filter_route_by_flood_zones(
        primary["route_coords"],
        flood_incidents,
        risk_buffer_km=0.5,
    )
    
    recommendation = ""
    if flooding_impact["affected"]:
        count = flooding_impact["risk_zones_crossed"]
        recommendation = (
            f"⚠️ WARNING: Primary route crosses {count} high-risk flood area(s). "
            f"Distance: {primary['distance_km']} km, Time: {primary['duration_seconds']//60} min. "
            f"Consider avoiding these zones or take precautions."
        )
    else:
        recommendation = (
            f"✅ Route is clear of reported flood zones. "
            f"Distance: {primary['distance_km']} km, Time: {primary['duration_seconds']//60} min."
        )
    
    return {
        "ok": True,
        "primary_route": {
            "coords": primary["route_coords"],
            "distance_km": primary["distance_km"],
            "duration_seconds": primary["duration_seconds"],
        },
        "flooding_risk": flooding_impact,
        "recommendation": recommendation,
    }
