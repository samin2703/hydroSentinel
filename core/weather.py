from __future__ import annotations

from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
import json


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_open_meteo_rainfall(lat: float, lon: float, timeout: int = 10) -> dict:
    """
    Fetch short-term rainfall from Open-Meteo (free, no API key).

    Returns rainfall estimates for current and next 1-3 hours in mm.
    """
    base_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "precipitation",
        "hourly": "precipitation",
        "forecast_hours": 4,
        "timezone": "auto",
    }

    url = f"{base_url}?{urlencode(params)}"

    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError):
        return {
            "ok": False,
            "error": "Unable to fetch live weather nowcast.",
        }

    current = payload.get("current", {})
    hourly = payload.get("hourly", {})
    hourly_precip = hourly.get("precipitation", []) or []

    current_mm = _safe_float(current.get("precipitation"), 0.0)
    h0 = _safe_float(hourly_precip[0], current_mm) if len(hourly_precip) > 0 else current_mm
    h1 = _safe_float(hourly_precip[1], h0) if len(hourly_precip) > 1 else h0
    h2 = _safe_float(hourly_precip[2], h1) if len(hourly_precip) > 2 else h1
    h3 = _safe_float(hourly_precip[3], h2) if len(hourly_precip) > 3 else h2

    return {
        "ok": True,
        "source": "Open-Meteo",
        "rain_now_mm": round(current_mm, 2),
        "rain_next_1h_mm": round(h1, 2),
        "rain_next_2h_mm": round(h2, 2),
        "rain_next_3h_mm": round(h3, 2),
        "rain_h0_mm": round(h0, 2),
    }
