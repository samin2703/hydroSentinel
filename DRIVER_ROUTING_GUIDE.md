# HydroSentinel: Driver Navigation & Routing System

## Overview
This document explains the new **Driver Navigation** feature added to HydroSentinel. It enables drivers to:
- Get real-time safe routes avoiding flood-affected areas
- Report blockages/floods they encounter
- Contribute to a crowdsourced flood awareness network

## Architecture

```
Authority App (Streamlit)          Driver App (Streamlit)
        ↓                                  ↓
        └──────→ FastAPI Backend ←────────┘
                      ↓
            Database + Route Engine
```

## Components

### 1. **Route Engine** (`core/route_engine.py`)
- Uses **OSRM** (Open Source Routing Machine) for free, open routing
- Checks if route passes through high-risk flood zones
- Returns:
  - Primary route coordinates
  - Distance & duration
  - Flood impact assessment
  - Driver recommendation

### 2. **FastAPI Backend** (`api.py`)
- Provides REST API endpoints for:
  - Route suggestions: `POST /api/v1/routes/suggest`
  - Incident reporting: `POST /api/v1/incidents/report`
  - Incident management: `GET/PUT /api/v1/incidents/*`
- Integrates with existing risk model & storage
- Handles image analysis for driver reports

### 3. **Driver App** (`driver_app.py`)
- Streamlit app for drivers (mobile-friendly)
- Two modes:
  - **Navigate**: Get route with flood warnings
  - **Report**: Submit blockage/flood photos in real-time

## How It Works

### Driver Navigation Flow
```
Driver enters: Start → Destination
       ↓
FastAPI fetches current HIGH-RISK incidents from DB
       ↓
OSRM calculates optimal route
       ↓
Route engine checks if route crosses flood zones (0.5 km buffer)
       ↓
Display: Route + Flood warnings + Recommendation
```

### Driver Reporting Flow
```
Driver sees blockage/flood
       ↓
Takes photo + fills report
       ↓
API analyzes image (blockage detection)
       ↓
Calculate flood risk
       ↓
Store in incidents database
       ↓
Automatically appears in ALL drivers' route suggestions
```

## Installation & Setup

### 1. Install Dependencies
```bash
cd c:\Users\sasam\OneDrive\Desktop\flood-alert
pip install -r requirements.txt
```

### 2. Setup OSRM (Routing Engine)
**Option A: Use Public OSRM (Recommended for Testing)**
- Backend uses `http://router.project-osrm.org` by default
- Free, no setup required
- Suitable for production if volume is low

**Option B: Self-Host OSRM (For Scale)**
```bash
# Docker method
docker run -t -d -p 5000:5000 -v /data:/data osrm/osrm-backend:v5.27.1 osrm-routed --algorithm mld /data/bangladesh-latest.osrm

# Then update api.py:
# API_URL = "http://localhost:5000"
```

Download Bangladesh OSM data: https://download.geofabrik.de/asia/bangladesh-latest.osm.pbf

### 3. Run the System

**Terminal 1: FastAPI Backend**
```bash
uvicorn api:app --reload --host 0.0.0.0 --port 8000
# Opens: http://localhost:8000
# Docs: http://localhost:8000/docs
```

**Terminal 2: Authority App** (existing)
```bash
streamlit run app.py
# Opens: http://localhost:8501
```

**Terminal 3: Driver App** (new)
```bash
streamlit run driver_app.py
# Opens: http://localhost:8502 (or next available port)
```

## API Endpoints

All endpoints are in `api.py`. Full documentation at `http://localhost:8000/docs`

### Route Suggestion
```
POST /api/v1/routes/suggest

Request:
{
  "start_lat": 23.8103,
  "start_lon": 90.3667,
  "end_lat": 23.7115,
  "end_lon": 90.4072
}

Response:
{
  "ok": true,
  "primary_route": {
    "coords": [[lon, lat], ...],
    "distance_km": 8.5,
    "duration_seconds": 900
  },
  "flooding_risk": {
    "affected": true,
    "high_risk_intersections": [
      {"id": 42, "lat": 23.81, "lon": 90.37, "risk_score": 82, "distance_km": 0.3}
    ],
    "risk_zones_crossed": 1
  },
  "recommendation": "⚠️ WARNING: Primary route crosses 1 high-risk flood area..."
}
```

### Incident Report (with Image)
```
POST /api/v1/incidents/report

Form Data:
- lat: 23.8103
- lon: 90.3667
- selected_area: "Mirpur"
- rainfall_mm_hr: 15
- reported_by: "driver"
- image: [multipart image file]

Response:
{
  "ok": true,
  "incident_id": 123,
  "risk_label": "High",
  "risk_score": 78.5,
  "message": "High flood risk. Immediate drain clearing recommended..."
}
```

### List Incidents (for dashboard)
```
GET /api/v1/incidents?status=Reported&risk_label=High&limit=50

Response:
{
  "ok": true,
  "count": 12,
  "incidents": [...]
}
```

### Update Status
```
PUT /api/v1/incidents/123/status

Request:
{
  "status": "Cleaned"
}
```

## Features Added

| Feature | Where | Status |
|---------|-------|--------|
| Route with flood warnings | Driver app | ✅ Complete |
| Driver incident reporting | Driver app | ✅ Complete |
| Image analysis on reports | API | ✅ Complete |
| Crowdsourced incidents | API → DB | ✅ Complete |
| FastAPI backend | api.py | ✅ Complete |
| OSRM integration | route_engine.py | ✅ Complete |
| Flood zone filtering | route_engine.py | ✅ Complete |

## Next Steps (Future Enhancements)

1. **Mobile App** → React Native with offline support
2. **Alternative Routes** → Return A/B/C route options with risk scores
3. **Real-time Notifications** → SMS/WhatsApp when flood reported nearby
4. **Route Preferences** → Driver chooses: "Fastest" vs "Safest"
5. **Analytics** → Track which routes fail most → preventive maintenance
6. **Gamification** → Reward drivers for timely reports
7. **Integration with City Traffic API** → Consider congestion + floods

## Testing

### Quick Test
```bash
# 1. Start all three services
# 2. Open driver app: http://localhost:8502
# 3. Click "Report Incident" → submit a fake incident
# 4. Click "Navigate" → query the route you just created
# 5. Route should show ⚠️ warning about flood
```

### Test API Directly
```bash
curl -X POST http://localhost:8000/api/v1/routes/suggest \
  -H "Content-Type: application/json" \
  -d '{
    "start_lat": 23.8103,
    "start_lon": 90.3667,
    "end_lat": 23.7115,
    "end_lon": 90.4072
  }'
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Failed to connect to backend" | Make sure `uvicorn api:app --reload` is running |
| OSRM timeout | Public OSRM may be slow; consider self-hosting or use Mapbox |
| Image analysis fails | Check PIL/Pillow is installed; image must be valid JPG/PNG |
| No flood zones appear in route | Check incidents are marked as "High" risk (>= 75 score) |

## Performance Notes

- **OSRM Public API**: ~1-2s per route calculation
- **Database queries**: < 100ms for up to 10,000 incidents
- **Recommended cache**: Store high-risk incidents in memory, refresh every 5 min
- **Scale limit**: FastAPI can handle ~1000 req/min on modest server

## Security Considerations (Before Going Live)

1. **API Authentication** → Add JWT tokens
2. **Rate Limiting** → Prevent abuse (100 req/min per driver)
3. **Input Validation** → Already in Pydantic models, good
4. **HTTPS** → Use TLS/SSL in production
5. **OSRM Hosting** → Don't expose if self-hosted without auth
6. **Image Upload Size** → Limit to 5MB in production

## File Structure
```
flood-alert/
├── app.py                    (Authority app)
├── driver_app.py             (NEW: Driver app)
├── api.py                    (NEW: FastAPI backend)
├── core/
│   ├── cv_model.py
│   ├── rainfall.py
│   ├── risk_engine.py
│   ├── storage.py
│   ├── weather.py
│   └── route_engine.py       (NEW: Route logic)
├── utils/
│   └── map_utils.py
└── requirements.txt          (updated)
```

---

**Questions?** Check the API docs: http://localhost:8000/docs
