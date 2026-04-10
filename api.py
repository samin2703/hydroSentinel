"""
FastAPI backend for HydroSentinel.
Provides endpoints for route calculation, incident reporting, and authorities.

Run with: uvicorn api:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import io

from core.cv_model import analyze_blockage
from core.route_engine import suggest_alternate_routes
from core.risk_engine import calculate_risk, calculate_short_term_probability
from core.storage import (
    init_submissions_db,
    insert_submission,
    fetch_submissions,
    update_submission_status,
)
from core.weather import get_open_meteo_rainfall
from utils.map_utils import extract_gps_from_exif, derive_geo_factors, get_nearest_area
from PIL import Image


app = FastAPI(title="HydroSentinel API", version="1.0.0")

# Enable CORS for cross-origin requests (driver app, web app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
def startup():
    init_submissions_db()


# ============================================================
# ROUTE SUGGESTIONS FOR DRIVERS
# ============================================================

class RouteSuggestionRequest(BaseModel):
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    osrm_url: Optional[str] = "http://router.project-osrm.org"


@app.post("/api/v1/routes/suggest")
async def suggest_routes(request: RouteSuggestionRequest):
    """
    Get route suggestions for a driver with flood zone warnings.
    
    Returns primary route, flood risk assessment, and recommendation.
    """
    # Fetch high-risk incidents (those marked as "High" risk)
    all_incidents = fetch_submissions()
    high_risk_incidents = [
        inc for inc in all_incidents
        if inc.get("risk_score", 0) >= 75
    ]
    
    result = suggest_alternate_routes(
        request.start_lat,
        request.start_lon,
        request.end_lat,
        request.end_lon,
        high_risk_incidents,
        request.osrm_url,
    )
    
    return JSONResponse(result)


# ============================================================
# INCIDENT REPORTING
# ============================================================

class IncidentReportRequest(BaseModel):
    lat: float
    lon: float
    selected_area: str
    rainfall_mm_hr: float
    blockage_score: Optional[float] = None
    description: Optional[str] = None
    reported_by: Optional[str] = None  # field worker name or "driver"


@app.post("/api/v1/incidents/report")
async def report_incident(
    incident: IncidentReportRequest,
    image: Optional[UploadFile] = File(None),
):
    """
    Submit a flood incident report (can include image analysis).
    Used by field workers or drivers.
    """
    blockage_score = incident.blockage_score or 0
    image_bytes = None
    image_name = None
    
    # If image provided, analyze it
    if image:
        try:
            image_bytes = await image.read()
            pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            blockage_result = analyze_blockage(pil_image)
            blockage_score = blockage_result["blockage_score"]
            image_name = image.filename
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Image analysis failed: {str(e)}")
    
    # Get weather data
    weather = get_open_meteo_rainfall(incident.lat, incident.lon)
    rainfall_for_risk = incident.rainfall_mm_hr
    if weather.get("ok"):
        rainfall_for_risk = float(weather["rain_next_1h_mm"])
    
    # Calculate geo factors
    geo_factors = derive_geo_factors(incident.lat, incident.lon)
    nearest_area_name, _, _ = get_nearest_area(incident.lat, incident.lon)
    
    # Calculate risk
    risk_result = calculate_risk(
        blockage_score=blockage_score,
        rainfall_mm_per_hr=rainfall_for_risk,
        location_factor=geo_factors["location_factor"],
    )
    
    # Calculate short-term probability
    if weather.get("ok"):
        short_term = calculate_short_term_probability(
            blockage_score=blockage_score,
            location_factor=geo_factors["location_factor"],
            rain_now_mm=float(weather["rain_now_mm"]),
            rain_next_1h_mm=float(weather["rain_next_1h_mm"]),
            rain_next_2h_mm=float(weather["rain_next_2h_mm"]),
        )
    else:
        short_term = calculate_short_term_probability(
            blockage_score=blockage_score,
            location_factor=geo_factors["location_factor"],
            rain_now_mm=rainfall_for_risk,
            rain_next_1h_mm=rainfall_for_risk,
            rain_next_2h_mm=rainfall_for_risk,
        )
    
    # Store in database
    record = {
        "submitted_at": datetime.utcnow().isoformat(),
        "selected_area": incident.selected_area,
        "nearest_area": nearest_area_name,
        "lat": incident.lat,
        "lon": incident.lon,
        "risk_label": risk_result["risk_label"],
        "risk_score": risk_result["risk_score"],
        "next_2h_probability": short_term["probability"],
        "blockage_score": blockage_score,
        "rainfall_used_mm_hr": rainfall_for_risk,
        "rainfall_source": "Driver Report" if incident.reported_by == "driver" else "Field Worker",
        "image_name": image_name,
        "image_bytes": image_bytes,
        "status": "Reported",
    }
    
    incident_id = insert_submission(record)
    
    return JSONResponse({
        "ok": True,
        "incident_id": incident_id,
        "risk_label": risk_result["risk_label"],
        "risk_score": risk_result["risk_score"],
        "message": risk_result["message"],
    })


# ============================================================
# INCIDENT MANAGEMENT
# ============================================================

class IncidentStatusUpdate(BaseModel):
    incident_id: int
    status: str  # "Reported", "Assigned", "Cleaned", "Verified"


@app.put("/api/v1/incidents/{incident_id}/status")
async def update_incident_status(incident_id: int, status_update: IncidentStatusUpdate):
    """Update incident status (for authority/cleanup teams)."""
    valid_statuses = ["Reported", "Assigned", "Cleaned", "Verified"]
    if status_update.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
        )
    
    try:
        update_submission_status(incident_id, status_update.status)
        return JSONResponse({"ok": True, "message": f"Status updated to {status_update.status}"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/incidents")
async def list_incidents(
    status: Optional[str] = None,
    risk_label: Optional[str] = None,
    limit: int = 100,
):
    """
    List all incidents with optional filtering.
    Used by authority dashboard.
    """
    all_incidents = fetch_submissions()
    
    if status:
        all_incidents = [inc for inc in all_incidents if inc["status"] == status]
    
    if risk_label:
        all_incidents = [inc for inc in all_incidents if inc["risk_label"] == risk_label]
    
    return JSONResponse({
        "ok": True,
        "count": len(all_incidents[:limit]),
        "incidents": all_incidents[:limit],
    })


@app.get("/api/v1/incidents/{incident_id}")
async def get_incident(incident_id: int):
    """Get details of a specific incident."""
    all_incidents = fetch_submissions()
    incident = next((inc for inc in all_incidents if inc["id"] == incident_id), None)
    
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    return JSONResponse({"ok": True, "incident": incident})


# ============================================================
# HEALTH & INFO
# ============================================================

@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return JSONResponse({"ok": True, "status": "HydroSentinel API running"})


@app.get("/")
async def root():
    """API info."""
    return JSONResponse({
        "name": "HydroSentinel API",
        "version": "1.0.0",
        "endpoints": {
            "routes": "/api/v1/routes/suggest",
            "incidents": {
                "report": "/api/v1/incidents/report",
                "list": "/api/v1/incidents",
                "get": "/api/v1/incidents/{incident_id}",
                "update_status": "/api/v1/incidents/{incident_id}/status",
            },
            "health": "/api/v1/health",
        }
    })
