from __future__ import annotations


def calculate_risk(
    blockage_score: float,
    rainfall_mm_per_hr: float,
    location_factor: float,
) -> dict:
    """
    Weighted risk model:
    - blockage_score contributes 50%
    - rainfall contributes up to 35%
    - location vulnerability contributes 15%
    """
    rainfall_norm = min(max(rainfall_mm_per_hr / 120.0, 0.0), 1.0)
    location_norm = min(max(location_factor, 0.0), 1.0)
    blockage_norm = min(max(blockage_score / 100.0, 0.0), 1.0)

    risk_score = (
        (blockage_norm * 0.50)
        + (rainfall_norm * 0.35)
        + (location_norm * 0.15)
    ) * 100

    if risk_score >= 75:
        risk_label = "High"
        message = "High flood risk. Immediate drain clearing and local alert recommended."
    elif risk_score >= 45:
        risk_label = "Moderate"
        message = "Moderate flood risk. Monitor rainfall and inspect nearby drains."
    else:
        risk_label = "Low"
        message = "Low immediate risk. Continue periodic monitoring."

    return {
        "risk_score": risk_score,
        "risk_label": risk_label,
        "message": message,
    }


def calculate_short_term_probability(
    blockage_score: float,
    location_factor: float,
    rain_now_mm: float,
    rain_next_1h_mm: float,
    rain_next_2h_mm: float,
) -> dict:
    """
    Estimate flood probability in the next 2 hours.

    Inputs:
    - blockage_score: 0-100
    - location_factor: 0-1 vulnerability
    - rain_*: hourly precipitation in mm
    """
    blockage_norm = min(max(blockage_score / 100.0, 0.0), 1.0)
    location_norm = min(max(location_factor, 0.0), 1.0)

    avg_2h_rain = (max(rain_next_1h_mm, 0.0) + max(rain_next_2h_mm, 0.0)) / 2.0
    peak_2h_rain = max(rain_next_1h_mm, rain_next_2h_mm, 0.0)
    rain_trend = max(rain_next_2h_mm - rain_now_mm, 0.0)

    avg_rain_norm = min(avg_2h_rain / 30.0, 1.0)
    peak_rain_norm = min(peak_2h_rain / 50.0, 1.0)
    trend_norm = min(rain_trend / 20.0, 1.0)

    probability = (
        (blockage_norm * 0.35)
        + (location_norm * 0.20)
        + (avg_rain_norm * 0.25)
        + (peak_rain_norm * 0.15)
        + (trend_norm * 0.05)
    ) * 100
    probability = max(0.0, min(100.0, probability))

    if probability >= 75:
        label = "Very Likely"
        message = "Very likely flooding in the next 2 hours. Trigger rapid response."
    elif probability >= 50:
        label = "Likely"
        message = "Flooding is likely within 2 hours. Monitor and pre-position teams."
    elif probability >= 30:
        label = "Possible"
        message = "Flooding is possible. Keep drains monitored and watch rainfall trend."
    else:
        label = "Unlikely"
        message = "Flooding in next 2 hours is currently unlikely."

    return {
        "probability": probability,
        "label": label,
        "message": message,
        "avg_2h_rain_mm": avg_2h_rain,
        "peak_2h_rain_mm": peak_2h_rain,
    }


def explain_risk_contributors(
    blockage_score: float,
    rainfall_mm_per_hr: float,
    location_factor: float,
    has_exact_gps: bool,
    has_live_weather: bool,
) -> dict:
    """Return weighted risk contributions and a confidence score for user trust."""
    blockage_norm = min(max(blockage_score / 100.0, 0.0), 1.0)
    rainfall_norm = min(max(rainfall_mm_per_hr / 120.0, 0.0), 1.0)
    location_norm = min(max(location_factor, 0.0), 1.0)

    comp_blockage = blockage_norm * 0.50
    comp_rain = rainfall_norm * 0.35
    comp_location = location_norm * 0.15
    total = comp_blockage + comp_rain + comp_location

    if total <= 0:
        shares = {
            "blockage": 0.0,
            "rainfall": 0.0,
            "location": 0.0,
        }
    else:
        shares = {
            "blockage": (comp_blockage / total) * 100.0,
            "rainfall": (comp_rain / total) * 100.0,
            "location": (comp_location / total) * 100.0,
        }

    sorted_contributors = sorted(shares.items(), key=lambda x: x[1], reverse=True)

    # Confidence heuristic: stronger when key inputs are live/precise and signal is decisive.
    confidence = 55.0
    confidence += 15.0 if has_exact_gps else 0.0
    confidence += 15.0 if has_live_weather else 0.0

    lead_gap = sorted_contributors[0][1] - sorted_contributors[1][1]
    confidence += min(max(lead_gap / 2.5, 0.0), 15.0)
    confidence = max(0.0, min(100.0, confidence))

    return {
        "confidence": confidence,
        "contributors": {
            "blockage": round(shares["blockage"], 1),
            "rainfall": round(shares["rainfall"], 1),
            "location": round(shares["location"], 1),
        },
        "top_contributors": [
            {
                "name": sorted_contributors[0][0],
                "share": round(sorted_contributors[0][1], 1),
            },
            {
                "name": sorted_contributors[1][0],
                "share": round(sorted_contributors[1][1], 1),
            },
        ],
    }