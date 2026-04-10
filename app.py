import streamlit as st
import folium
import base64
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen
from folium.plugins import MarkerCluster
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from streamlit_folium import st_folium

from core.cv_model import analyze_blockage
from core.rainfall import get_rainfall_options
from core.risk_engine import (
    calculate_risk,
    calculate_short_term_probability,
    explain_risk_contributors,
)
from core.storage import (
    clear_submissions,
    fetch_submissions,
    init_submissions_db,
    insert_submission,
    update_submission_status,
)
from core.weather import get_open_meteo_rainfall
from utils.map_utils import (
    derive_geo_factors,
    extract_gps_from_exif,
    get_area_center,
    get_location_options,
    get_location_meta,
    get_nearest_area,
)


st.set_page_config(page_title="HydroSentinel", layout="wide")
INCIDENT_STATUSES = ["Reported", "Assigned", "Cleaned", "Verified"]


def apply_professional_theme() -> None:
    st.markdown(
        """
        <style>
            :root {
                --hs-bg: #0b1220;
                --hs-surface: #111b2e;
                --hs-border: #25324a;
                --hs-text: #e6edf7;
                --hs-muted: #a7b3c8;
                --hs-primary: #2f6fd6;
                --hs-glass: rgba(17, 27, 46, 0.55);
                --hs-glow: rgba(74, 131, 255, 0.22);
            }

            .stApp {
                color: var(--hs-text);
                background: radial-gradient(circle at 10% 0%, #18253f 0%, #0b1220 45%, #070c16 100%);
            }

            [data-testid="stSidebar"] {
                background: rgba(15, 23, 40, 0.78);
                backdrop-filter: blur(10px);
                border-right: 1px solid rgba(255, 255, 255, 0.08);
            }

            [data-testid="block-container"] {
                max-width: 1320px;
                padding-top: 1.2rem;
                padding-bottom: 2rem;
            }

            h1, h2, h3 {
                color: var(--hs-text);
                letter-spacing: 0.1px;
            }

            .stCaption {
                color: var(--hs-muted) !important;
                font-size: 0.92rem;
            }

            p, label, div {
                color: var(--hs-text);
            }

            [data-testid="stMetric"] {
                border: 1px solid var(--hs-border);
                background: linear-gradient(180deg, rgba(28, 44, 70, 0.55) 0%, var(--hs-glass) 100%);
                border-radius: 12px;
                padding: 0.8rem 0.9rem;
                box-shadow: 0 6px 16px rgba(0, 0, 0, 0.25);
                backdrop-filter: blur(8px);
                transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
            }

            [data-testid="stMetric"]:hover {
                transform: translateY(-2px);
                border-color: rgba(127, 179, 255, 0.45);
                box-shadow: 0 10px 24px rgba(0, 0, 0, 0.28), 0 0 0 1px var(--hs-glow) inset;
            }

            [data-testid="stMetricLabel"] {
                color: var(--hs-muted);
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                font-size: 0.72rem;
            }

            [data-testid="stMetricValue"] {
                color: var(--hs-text);
                font-weight: 700;
            }

            .stButton > button {
                border-radius: 8px;
                transition: transform 0.16s ease, box-shadow 0.16s ease;
            }

            .stButton > button:hover {
                transform: translateY(-1px);
                box-shadow: 0 8px 18px rgba(0, 0, 0, 0.28);
            }

            .stButton > button[kind="primary"] {
                background: linear-gradient(135deg, #2f6fd6 0%, #2558aa 100%);
                border: 1px solid #3e79dc;
                box-shadow: 0 8px 20px rgba(47, 111, 214, 0.28);
            }

            .stTextInput > div > div > input,
            .stTextArea textarea,
            .stNumberInput input,
            .stSelectbox [data-baseweb="select"] > div {
                background: rgba(16, 27, 44, 0.62) !important;
                border: 1px solid rgba(136, 163, 201, 0.28) !important;
                border-radius: 10px !important;
                color: var(--hs-text) !important;
                backdrop-filter: blur(6px);
            }

            [data-testid="stExpander"] {
                background: rgba(16, 27, 44, 0.48);
                border: 1px solid rgba(136, 163, 201, 0.2);
                border-radius: 10px;
                backdrop-filter: blur(6px);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=600)
def get_live_rainfall(lat: float, lon: float) -> dict:
    return get_open_meteo_rainfall(lat, lon)


def build_incident_csv(record: dict) -> str:
    output = io.StringIO()
    fields = [
        "id",
        "submitted_at_str",
        "contributor_name",
        "contributor_id",
        "status",
        "selected_area",
        "nearest_area",
        "lat",
        "lon",
        "risk_label",
        "risk_score",
        "next_2h_probability",
        "blockage_score",
        "rainfall_used_mm_hr",
        "rainfall_source",
        "image_name",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerow({k: record.get(k, "") for k in fields})
    return output.getvalue()


def build_incident_json(record: dict) -> str:
    data = {}
    for key, value in record.items():
        if key == "image_bytes":
            continue
        if isinstance(value, datetime):
            data[key] = value.isoformat()
        else:
            data[key] = value
    image_bytes = record.get("image_bytes")
    if image_bytes:
        data["image_base64"] = base64.b64encode(image_bytes).decode("ascii")
    else:
        data["image_base64"] = None
    return json.dumps(data, indent=2)


def build_incident_pdf(record: dict) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "HydroSentinel - Authority Incident Report")
    y -= 28

    pdf.setFont("Helvetica", 10)
    lines = [
        f"Incident ID: {record.get('id', 'N/A')}",
        f"Timestamp: {record.get('submitted_at_str', 'N/A')}",
        f"Contributor Name: {record.get('contributor_name', 'N/A')}",
        f"Contributor ID: {record.get('contributor_id', 'N/A')}",
        f"Status: {record.get('status', 'N/A')}",
        f"Area: {record.get('selected_area', 'N/A')}",
        f"Nearest Area: {record.get('nearest_area', 'N/A')}",
        f"GPS: {record.get('lat', 'N/A')}, {record.get('lon', 'N/A')}",
        f"Risk: {record.get('risk_label', 'N/A')} ({record.get('risk_score', 'N/A')}/100)",
        f"Flood Probability Next 2h: {record.get('next_2h_probability', 'N/A')}%",
        f"Blockage: {record.get('blockage_score', 'N/A')}%",
        f"Rainfall Used: {record.get('rainfall_used_mm_hr', 'N/A')} mm/hr",
        f"Rainfall Source: {record.get('rainfall_source', 'N/A')}",
    ]

    for line in lines:
        pdf.drawString(40, y, line)
        y -= 16

    image_bytes = record.get("image_bytes")
    if image_bytes:
        y -= 8
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(40, y, "Submitted Drain Image")
        y -= 10
        try:
            image_stream = io.BytesIO(image_bytes)
            image = Image.open(image_stream)
            max_w = width - 80
            max_h = 240
            scale = min(max_w / image.width, max_h / image.height, 1.0)
            draw_w = image.width * scale
            draw_h = image.height * scale
            y_image = max(y - draw_h - 8, 30)
            pdf.drawImage(
                ImageReader(image),
                40,
                y_image,
                width=draw_w,
                height=draw_h,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pdf.setFont("Helvetica", 10)
            pdf.drawString(40, y - 16, "Image preview unavailable in PDF export.")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def generate_ollama_summary(
    risk: dict,
    short_term: dict,
    explanation: dict,
    location_name: str,
    nearest_area: str,
    rainfall_mm_hr: float,
    timeout: int = 20,
) -> str | None:
    """Generate an operational summary using local Ollama (llama3.2)."""
    prompt = (
        "You are an operations assistant for flood response. "
        "Summarize this incident in 4 concise bullet points for field teams: "
        "(1) risk status, (2) immediate action, (3) next-2h expectation, "
        "(4) monitoring priority. Keep total under 90 words.\n\n"
        f"Location: {location_name} (nearest area: {nearest_area})\n"
        f"Risk label: {risk.get('risk_label')}\n"
        f"Risk score: {risk.get('risk_score', 0):.1f}/100\n"
        f"Flood probability next 2h: {short_term.get('probability', 0):.1f}% ({short_term.get('label')})\n"
        f"Rainfall used: {rainfall_mm_hr:.2f} mm/hr\n"
        f"Top contributors: {explanation.get('top_contributors', [])}\n"
    )

    payload = {
        "model": "llama3.2",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
        },
    }

    req = Request(
        url="http://localhost:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None

    summary = str(data.get("response", "")).strip()
    return summary or None


def build_mock_alerts(
    risk: dict,
    short_term: dict,
    location_name: str,
    nearest_area: str,
) -> list[dict]:
    """Create mock alerts for demo purposes across operational channels."""
    risk_score = float(risk.get("risk_score", 0.0))
    probability = float(short_term.get("probability", 0.0))

    severity = "Low"
    if risk_score >= 75 or probability >= 70:
        severity = "Critical"
    elif risk_score >= 45 or probability >= 45:
        severity = "Warning"

    base_message = (
        f"{severity} flood condition in {location_name} (nearest: {nearest_area}). "
        f"Risk {risk_score:.1f}/100, next 2h probability {probability:.1f}%."
    )

    alerts = [
        {
            "channel": "Control Room Dashboard",
            "priority": severity,
            "message": base_message,
        },
        {
            "channel": "Field Operations SMS (Mock)",
            "priority": severity,
            "message": f"Dispatch readiness update: {base_message}",
        },
        {
            "channel": "Email to City Authority (Mock)",
            "priority": severity,
            "message": f"Incident advisory: {base_message}",
        },
    ]

    return alerts


def calculate_dashboard_kpis(incidents: list[dict]) -> dict:
    """Calculate key performance indicators from incidents."""
    if not incidents:
        return {
            "total": 0,
            "high_risk": 0,
            "avg_risk": 0.0,
            "most_affected_area": "N/A",
            "top_contributor": "N/A",
            "top_contributor_count": 0,
            "reported_count": 0,
            "cleaned_count": 0,
        }
    
    total = len(incidents)
    high_risk = sum(1 for inc in incidents if inc.get("risk_score", 0) >= 75)
    avg_risk = sum(inc.get("risk_score", 0) for inc in incidents) / total if total > 0 else 0
    
    # Most affected area
    area_counts = {}
    for inc in incidents:
        area = inc.get("nearest_area", "Unknown")
        area_counts[area] = area_counts.get(area, 0) + 1
    most_affected_area = max(area_counts, key=area_counts.get) if area_counts else "N/A"

    contributor_counts = {}
    named_contributor_counts = {}
    for inc in incidents:
        contributor = (inc.get("contributor_name") or "Anonymous").strip() or "Anonymous"
        contributor_counts[contributor] = contributor_counts.get(contributor, 0) + 1
        if contributor.lower() != "anonymous":
            named_contributor_counts[contributor] = named_contributor_counts.get(contributor, 0) + 1

    if named_contributor_counts:
        top_contributor = max(named_contributor_counts, key=named_contributor_counts.get)
        top_contributor_count = named_contributor_counts.get(top_contributor, 0)
    else:
        top_contributor = "Anonymous"
        top_contributor_count = contributor_counts.get("Anonymous", 0)
    
    # Status breakdown
    reported_count = sum(1 for inc in incidents if inc.get("status") == "Reported")
    cleaned_count = sum(1 for inc in incidents if inc.get("status") == "Cleaned")
    
    return {
        "total": total,
        "high_risk": high_risk,
        "avg_risk": round(avg_risk, 1),
        "most_affected_area": most_affected_area,
        "top_contributor": top_contributor,
        "top_contributor_count": top_contributor_count,
        "reported_count": reported_count,
        "cleaned_count": cleaned_count,
    }


def build_heatmap_with_clusters(incidents: list[dict]) -> folium.Map:
    """Build a heatmap showing incident density and risk levels."""
    default_center = [23.8103, 90.3667]
    
    heatmap = folium.Map(
        location=default_center,
        zoom_start=11,
        tiles="OpenStreetMap",
    )
    
    # Add marker cluster for all incidents
    marker_cluster = MarkerCluster().add_to(heatmap)
    
    # Color code by risk level and add to cluster
    for incident in incidents:
        lat = incident.get("lat")
        lon = incident.get("lon")
        risk_score = incident.get("risk_score", 0)
        risk_label = incident.get("risk_label", "Unknown")
        status = incident.get("status", "Unknown")
        
        # Determine color
        if risk_score >= 75:
            color = "red"
            icon_color = "white"
        elif risk_score >= 45:
            color = "orange"
            icon_color = "white"
        else:
            color = "green"
            icon_color = "white"
        
        # Popup with incident details
        popup_text = f"""
        <b>Risk Level:</b> {risk_label} ({risk_score:.1f}/100)<br>
        <b>Status:</b> {status}<br>
        <b>Contributor:</b> {incident.get('contributor_name', 'Anonymous')} ({incident.get('contributor_id', 'N/A')})<br>
        <b>Area:</b> {incident.get('nearest_area', 'N/A')}<br>
        <b>Blockage:</b> {incident.get('blockage_score', 'N/A'):.1f}%<br>
        <b>ID:</b> {incident.get('id', 'N/A')}
        """
        
        folium.CircleMarker(
            location=[lat, lon],
            radius=8,
            popup=folium.Popup(popup_text, max_width=250),
            color=color,
            fill=True,
            fillColor=color,
            fillOpacity=0.7,
            weight=2,
            tooltip=f"{risk_label} - {incident.get('nearest_area', 'N/A')}",
        ).add_to(marker_cluster)
    
    return heatmap


def main() -> None:
    apply_professional_theme()
    st.title("HydroSentinel")
    st.caption("Flood risk prediction from drain image blockage + rainfall + location")
    init_submissions_db()
    if "alert_history" not in st.session_state:
        st.session_state.alert_history = []
    
    # Fetch incidents for dashboard
    all_incidents = fetch_submissions()
    kpis = calculate_dashboard_kpis(all_incidents)
    
    # Dashboard KPIs
    st.subheader("Dashboard Overview")
    kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5, kpi_col6 = st.columns(6)
    
    with kpi_col1:
        st.metric("Total Incidents", kpis["total"])
    with kpi_col2:
        st.metric("High Risk", kpis["high_risk"], delta=f"of {kpis['total']}")
    with kpi_col3:
        st.metric("Avg Risk Score", f"{kpis['avg_risk']}/100")
    with kpi_col4:
        st.metric("Pending Reports", kpis["reported_count"])
    with kpi_col5:
        st.metric("Cleaned", kpis["cleaned_count"])
    with kpi_col6:
        st.metric("Top Named Contributor", kpis["top_contributor_count"])
    
    st.metric("Most Affected Area", kpis["most_affected_area"])
    st.caption(
        f"Top named contributor by report count: {kpis['top_contributor']} ({kpis['top_contributor_count']} reports)"
    )
    
    st.divider()
    
    # Heatmap section
    st.subheader("Incident Heatmap")
    st.caption("Red = High Risk | Orange = Moderate | Green = Low Risk")
    
    if all_incidents:
        heatmap = build_heatmap_with_clusters(all_incidents)
        st_folium(heatmap, width=1200, height=500, key="incident_heatmap")
    else:
        st.info("No incidents yet. Reports will appear here.")
    
    st.divider()

    col1, col2 = st.columns([1.2, 1])
    detected_coords = None
    blockage_result = None
    selected_media = None
    selected_media_name = None

    with col1:
        st.subheader("1) Drain Visual Input")
        if "enable_live_capture" not in st.session_state:
            st.session_state.enable_live_capture = False

        media_col1, media_col2 = st.columns(2)
        with media_col1:
            uploaded_file = st.file_uploader(
                "Upload photo",
                type=["jpg", "jpeg", "png"],
            )
        with media_col2:
            if st.button("Start Live Capture", use_container_width=True):
                st.session_state.enable_live_capture = True
            if st.button("Stop Live Capture", use_container_width=True):
                st.session_state.enable_live_capture = False

            camera_file = None
            if st.session_state.enable_live_capture:
                camera_file = st.camera_input("Live camera capture")
            else:
                st.caption("Live camera is off. Click Start Live Capture to enable.")

        if camera_file is not None:
            selected_media = camera_file
            selected_media_name = "live_capture.jpg"
            st.caption("Using live camera capture for analysis.")
        elif uploaded_file is not None:
            selected_media = uploaded_file
            selected_media_name = uploaded_file.name

        if selected_media is not None:
            selected_media.seek(0)
            raw_image = Image.open(selected_media)
            detected_coords = extract_gps_from_exif(raw_image)

            selected_media.seek(0)
            image = Image.open(selected_media).convert("RGB")
            # Support both newer and older Streamlit image sizing args.
            try:
                st.image(image, caption="Selected drain image", use_container_width=True)
            except TypeError:
                st.image(image, caption="Selected drain image", use_column_width=True)

            if detected_coords is not None:
                st.success(
                    f"GPS detected from photo EXIF: {detected_coords[0]:.6f}, {detected_coords[1]:.6f}"
                )
            else:
                st.info("No EXIF GPS found in this photo. Use map pin in Context Inputs.")

            blockage_result = analyze_blockage(image)

            st.markdown("**Blockage Analysis**")
            st.write(f"Blockage score: **{blockage_result['blockage_score']:.1f}%**")
            st.write(f"Detected status: **{blockage_result['label']}**")
            st.progress(min(int(blockage_result["blockage_score"]), 100))

    with col2:
        st.subheader("2) Context Inputs")
        st.markdown("**Contributor Tracking**")
        contributor_name = st.text_input("Contributor Name", value="")
        contributor_id = st.text_input("Contributor ID", value="")

        rainfall_choice = st.selectbox("Rainfall (mm/hr)", get_rainfall_options())

        location_options = get_location_options()
        location_choice = st.selectbox("Location", location_options)
        location_meta = get_location_meta(location_choice)

        default_lat, default_lon = get_area_center(location_choice)
        exact_lat = default_lat
        exact_lon = default_lon

        st.markdown("**Exact Location**")
        use_pin_override = False
        if detected_coords is not None:
            exact_lat, exact_lon = detected_coords
            use_pin_override = st.checkbox(
                "Override detected photo GPS by clicking a map pin",
                value=False,
            )
        else:
            st.caption("No photo GPS detected. Click map to set exact location pin.")
            use_pin_override = True

        if "map_pin_coords" not in st.session_state:
            st.session_state.map_pin_coords = None

        if use_pin_override:
            if st.session_state.map_pin_coords is not None:
                map_center = [
                    st.session_state.map_pin_coords["lat"],
                    st.session_state.map_pin_coords["lon"],
                ]
            else:
                map_center = [default_lat, default_lon]

            location_map = folium.Map(location=map_center, zoom_start=12)
            folium.Marker(
                [default_lat, default_lon],
                tooltip=f"Selected area center: {location_choice}",
                icon=folium.Icon(color="blue", icon="info-sign"),
            ).add_to(location_map)

            if st.session_state.map_pin_coords is not None:
                folium.Marker(
                    [
                        st.session_state.map_pin_coords["lat"],
                        st.session_state.map_pin_coords["lon"],
                    ],
                    tooltip="Pinned exact location",
                    icon=folium.Icon(color="red", icon="map-marker"),
                ).add_to(location_map)

            map_state = st_folium(location_map, width=520, height=300, key="location_pin_map")

            last_clicked = map_state.get("last_clicked") if isinstance(map_state, dict) else None
            if last_clicked:
                st.session_state.map_pin_coords = {
                    "lat": float(last_clicked["lat"]),
                    "lon": float(last_clicked["lng"]),
                }

            if st.session_state.map_pin_coords is not None:
                exact_lat = float(st.session_state.map_pin_coords["lat"])
                exact_lon = float(st.session_state.map_pin_coords["lon"])
                st.success(f"Pinned location: {exact_lat:.6f}, {exact_lon:.6f}")

            reset_pin_col, _ = st.columns([1, 2])
            with reset_pin_col:
                if st.button("Reset Pin", use_container_width=True):
                    st.session_state.map_pin_coords = None
                    st.rerun()

            if st.session_state.map_pin_coords is None and detected_coords is None:
                st.warning("Pin not set yet. Using selected area center temporarily.")

        geo_factors = derive_geo_factors(exact_lat, exact_lon)
        nearest_area_name, _, nearest_area_distance_km = get_nearest_area(exact_lat, exact_lon)
        combined_location_factor = min(
            1.0,
            max(
                0.0,
                (location_meta["location_factor"] * 0.40)
                + (geo_factors["location_factor"] * 0.60),
            ),
        )

        st.markdown("**Rainfall Source**")
        rainfall_source = st.radio(
            "Choose rainfall input mode",
            ["Live Nowcast (Open-Meteo)", "Manual"],
            horizontal=True,
        )

        live_weather = None
        rainfall_for_risk = float(rainfall_choice)
        if rainfall_source == "Live Nowcast (Open-Meteo)":
            live_weather = get_live_rainfall(exact_lat, exact_lon)
            if live_weather.get("ok"):
                rainfall_for_risk = float(live_weather["rain_next_1h_mm"])
                st.write(
                    "Live rainfall (mm): "
                    f"now {live_weather['rain_now_mm']:.2f}, "
                    f"+1h {live_weather['rain_next_1h_mm']:.2f}, "
                    f"+2h {live_weather['rain_next_2h_mm']:.2f}, "
                    f"+3h {live_weather['rain_next_3h_mm']:.2f}"
                )
            else:
                st.warning("Live weather unavailable. Falling back to manual rainfall value.")

        st.markdown("**Location Snapshot**")
        st.write(f"Zone type: {location_meta['zone_type']}")
        st.write(f"Drain capacity index: {location_meta['drain_capacity']}")
        st.write(f"Flood history: {location_meta['flood_history']}")
        st.write(f"Terrain: {location_meta['terrain']}")
        st.write(f"Nearby water body: {location_meta['nearby_water_body']}")
        st.write(f"Exact lat/lon used: {geo_factors['lat']:.6f}, {geo_factors['lon']:.6f}")
        st.write(
            f"Nearest Dhaka area by pin: {nearest_area_name} ({nearest_area_distance_km:.2f} km)"
        )
        st.write(
            "Geo factors: "
            f"river/canal {geo_factors['distance_to_river_or_canal_km']:.2f} km, "
            f"hotspot {geo_factors['distance_to_hotspot_km']:.2f} km, "
            f"lowland {geo_factors['distance_to_lowland_km']:.2f} km"
        )
        st.write(
            f"Combined location vulnerability: {combined_location_factor:.2f} "
            f"(area {location_meta['location_factor']:.2f}, geo {geo_factors['location_factor']:.2f})"
        )

        st.subheader("3) Risk Prediction")
        if "latest_risk_output" not in st.session_state:
            st.session_state.latest_risk_output = None

        if st.button("Calculate Flood Risk", type="primary", use_container_width=True):
            if blockage_result is None:
                st.warning("Please upload a photo or capture one from live camera first.")
            else:
                risk = calculate_risk(
                    blockage_score=blockage_result["blockage_score"],
                    rainfall_mm_per_hr=rainfall_for_risk,
                    location_factor=combined_location_factor,
                )

                if live_weather and live_weather.get("ok"):
                    short_term = calculate_short_term_probability(
                        blockage_score=blockage_result["blockage_score"],
                        location_factor=combined_location_factor,
                        rain_now_mm=float(live_weather["rain_now_mm"]),
                        rain_next_1h_mm=float(live_weather["rain_next_1h_mm"]),
                        rain_next_2h_mm=float(live_weather["rain_next_2h_mm"]),
                    )
                else:
                    short_term = calculate_short_term_probability(
                        blockage_score=blockage_result["blockage_score"],
                        location_factor=combined_location_factor,
                        rain_now_mm=rainfall_for_risk,
                        rain_next_1h_mm=rainfall_for_risk,
                        rain_next_2h_mm=rainfall_for_risk,
                    )

                has_exact_gps = bool(detected_coords) or bool(
                    st.session_state.map_pin_coords is not None
                )
                has_live_weather = bool(
                    rainfall_source == "Live Nowcast (Open-Meteo)"
                    and live_weather
                    and live_weather.get("ok")
                )
                explanation = explain_risk_contributors(
                    blockage_score=blockage_result["blockage_score"],
                    rainfall_mm_per_hr=rainfall_for_risk,
                    location_factor=combined_location_factor,
                    has_exact_gps=has_exact_gps,
                    has_live_weather=has_live_weather,
                )

                submitted_at = datetime.now(timezone.utc)

                st.session_state.latest_risk_output = {
                    "risk": risk,
                    "short_term": short_term,
                    "explanation": explanation,
                    "alerts": build_mock_alerts(
                        risk=risk,
                        short_term=short_term,
                        location_name=location_choice,
                        nearest_area=nearest_area_name,
                    ),
                    "ollama_summary": generate_ollama_summary(
                        risk=risk,
                        short_term=short_term,
                        explanation=explanation,
                        location_name=location_choice,
                        nearest_area=nearest_area_name,
                        rainfall_mm_hr=float(rainfall_for_risk),
                    ),
                }

                for alert in st.session_state.latest_risk_output["alerts"]:
                    st.session_state.alert_history.insert(
                        0,
                        {
                            "time_utc": submitted_at.strftime("%Y-%m-%d %H:%M:%S"),
                            "channel": alert["channel"],
                            "priority": alert["priority"],
                            "location": location_choice,
                            "message": alert["message"],
                        },
                    )

                st.session_state.alert_history = st.session_state.alert_history[:30]

                image_bytes = selected_media.getvalue() if selected_media is not None else None
                insert_submission(
                    {
                        "submitted_at": submitted_at.isoformat(),
                        "contributor_name": contributor_name.strip() or "Anonymous",
                        "contributor_id": contributor_id.strip() or None,
                        "selected_area": location_choice,
                        "nearest_area": nearest_area_name,
                        "lat": round(exact_lat, 6),
                        "lon": round(exact_lon, 6),
                        "risk_label": risk["risk_label"],
                        "risk_score": round(float(risk["risk_score"]), 1),
                        "next_2h_probability": round(float(short_term["probability"]), 1),
                        "blockage_score": round(float(blockage_result["blockage_score"]), 1),
                        "rainfall_used_mm_hr": round(float(rainfall_for_risk), 2),
                        "rainfall_source": rainfall_source,
                        "status": "Reported",
                        "image_name": selected_media_name,
                        "image_bytes": image_bytes,
                    }
                )

        if st.session_state.latest_risk_output is not None:
            risk = st.session_state.latest_risk_output["risk"]
            short_term = st.session_state.latest_risk_output["short_term"]
            explanation = st.session_state.latest_risk_output["explanation"]
            alerts = st.session_state.latest_risk_output.get("alerts", [])
            ollama_summary = st.session_state.latest_risk_output.get("ollama_summary")

            st.markdown("### Result")
            st.metric("Risk Level", risk["risk_label"])
            st.write(f"Risk score: **{risk['risk_score']:.1f} / 100**")
            st.progress(min(int(risk["risk_score"]), 100))
            st.info(risk["message"])

            st.markdown("### Short-Term Forecast")
            st.metric("Flood Probability (Next 2h)", f"{short_term['probability']:.1f}%")
            st.write(f"Likelihood: **{short_term['label']}**")
            st.write(
                "Rain drivers: "
                f"avg 2h rain {short_term['avg_2h_rain_mm']:.2f} mm, "
                f"peak hour {short_term['peak_2h_rain_mm']:.2f} mm"
            )
            st.info(short_term["message"])

            st.markdown("### 5) Confidence + Explanation")
            st.metric("Model Confidence", f"{explanation['confidence']:.1f}%")
            st.write(
                "Top contributors: "
                f"{explanation['top_contributors'][0]['name'].title()} "
                f"{explanation['top_contributors'][0]['share']:.1f}%, "
                f"{explanation['top_contributors'][1]['name'].title()} "
                f"{explanation['top_contributors'][1]['share']:.1f}%"
            )
            st.write(
                "Contribution split: "
                f"Blockage {explanation['contributors']['blockage']:.1f}%, "
                f"Rainfall {explanation['contributors']['rainfall']:.1f}%, "
                f"Location {explanation['contributors']['location']:.1f}%"
            )

            st.markdown("### 6) AI Operational Summary")
            if ollama_summary:
                st.write(ollama_summary)
            else:
                st.caption(
                    "AI summary unavailable. Ensure Ollama is running and model llama3.2 is installed."
                )

            st.markdown("### 7) Alert Center (Mock)")
            if alerts:
                for alert in alerts:
                    if alert["priority"] == "Critical":
                        st.error(f"{alert['channel']}: {alert['message']}")
                    elif alert["priority"] == "Warning":
                        st.warning(f"{alert['channel']}: {alert['message']}")
                    else:
                        st.info(f"{alert['channel']}: {alert['message']}")
            else:
                st.caption("No alerts generated for current result.")

            if st.session_state.alert_history:
                st.markdown("**Recent alert log**")
                st.dataframe(st.session_state.alert_history[:10], use_container_width=True)

    st.divider()
    st.subheader("4) Hotspot Map Dashboard")
    st.caption("City-level monitoring view of all submitted assessments.")

    submissions = fetch_submissions()
    if not submissions:
        st.info("No submissions yet. Run at least one risk prediction to populate the dashboard.")
    else:
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([1, 1.2, 1, 1])

        with filter_col1:
            time_filter = st.selectbox(
                "Time window",
                ["Last 1 hour", "Last 6 hours", "Last 24 hours", "All time"],
                index=2,
            )

        all_areas = sorted({item["selected_area"] for item in submissions})
        with filter_col2:
            area_filter = st.multiselect(
                "Area filter",
                options=all_areas,
                default=all_areas,
            )

        risk_levels = ["Low", "Moderate", "High"]
        with filter_col3:
            risk_filter = st.multiselect(
                "Risk level filter",
                options=risk_levels,
                default=risk_levels,
            )

        with filter_col4:
            status_filter = st.multiselect(
                "Incident status",
                options=INCIDENT_STATUSES,
                default=INCIDENT_STATUSES,
            )

        now_utc = datetime.now(timezone.utc)
        if time_filter == "Last 1 hour":
            cutoff = now_utc - timedelta(hours=1)
        elif time_filter == "Last 6 hours":
            cutoff = now_utc - timedelta(hours=6)
        elif time_filter == "Last 24 hours":
            cutoff = now_utc - timedelta(hours=24)
        else:
            cutoff = datetime.min.replace(tzinfo=timezone.utc)

        filtered = [
            item
            for item in submissions
            if item["submitted_at"] >= cutoff
            and item["selected_area"] in area_filter
            and item["risk_label"] in risk_filter
            and item.get("status", "Reported") in status_filter
        ]

        summary_col1, summary_col2, summary_col3 = st.columns(3)
        with summary_col1:
            st.metric("Visible Submissions", len(filtered))
        with summary_col2:
            high_count = sum(1 for item in filtered if item["risk_label"] == "High")
            st.metric("High Risk Count", high_count)
        with summary_col3:
            avg_prob = (
                sum(item["next_2h_probability"] for item in filtered) / len(filtered)
                if filtered
                else 0.0
            )
            st.metric("Avg Next 2h Probability", f"{avg_prob:.1f}%")

        dashboard_map = folium.Map(location=[23.8103, 90.4125], zoom_start=11)
        marker_cluster = MarkerCluster(name="Submission Clusters").add_to(dashboard_map)
        risk_colors = {
            "Low": "green",
            "Moderate": "orange",
            "High": "red",
        }

        for item in filtered:
            color = risk_colors.get(item["risk_label"], "blue")
            popup_html = (
                f"<b>ID:</b> {item['id']}<br>"
                f"<b>Area:</b> {item['selected_area']}<br>"
                f"<b>Nearest area:</b> {item['nearest_area']}<br>"
                f"<b>Risk:</b> {item['risk_label']} ({item['risk_score']:.1f}/100)<br>"
                f"<b>Next 2h flood probability:</b> {item['next_2h_probability']:.1f}%<br>"
                f"<b>Blockage:</b> {item['blockage_score']:.1f}%<br>"
                f"<b>Rainfall used:</b> {item['rainfall_used_mm_hr']:.2f} mm/hr<br>"
                f"<b>Status:</b> {item.get('status', 'Reported')}<br>"
                f"<b>Time:</b> {item['submitted_at_str']}"
            )

            folium.CircleMarker(
                location=[item["lat"], item["lon"]],
                radius=6 + (item["risk_score"] / 25.0),
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.75,
                popup=folium.Popup(popup_html, max_width=340),
                tooltip=f"{item['selected_area']} - {item['risk_label']}",
            ).add_to(marker_cluster)

        legend_html = """
        <div style="
            position: fixed;
            bottom: 20px;
            left: 20px;
            z-index: 9999;
            background: white;
            border: 2px solid #444;
            border-radius: 6px;
            padding: 10px 12px;
            font-size: 12px;
            line-height: 1.6;
        ">
            <strong>Risk Legend</strong><br>
            <span style="color: green;">&#9679;</span> Low<br>
            <span style="color: orange;">&#9679;</span> Moderate<br>
            <span style="color: red;">&#9679;</span> High
        </div>
        """
        dashboard_map.get_root().html.add_child(folium.Element(legend_html))
        folium.LayerControl().add_to(dashboard_map)

        st_folium(dashboard_map, width=1100, height=420, key="hotspot_dashboard_map")

        if filtered:
            st.markdown("**Filtered submissions**")
            st.dataframe(
                [
                    {
                        "Time (UTC)": item["submitted_at_str"],
                        "Incident ID": item["id"],
                        "Area": item["selected_area"],
                        "Contributor": item.get("contributor_name") or "Anonymous",
                        "Contributor ID": item.get("contributor_id") or "N/A",
                        "Nearest Area": item["nearest_area"],
                        "Risk": item["risk_label"],
                        "Risk Score": item["risk_score"],
                        "Status": item.get("status", "Reported"),
                        "Flood Prob 2h (%)": item["next_2h_probability"],
                        "Latitude": item["lat"],
                        "Longitude": item["lon"],
                    }
                    for item in sorted(filtered, key=lambda x: x["submitted_at"], reverse=True)
                ],
                use_container_width=True,
            )
        else:
            st.warning("No submissions match current filters.")

        st.markdown("### 6) Incident Workflow")
        if filtered:
            incident_options = {
                (
                    f"#{item['id']} | {item['selected_area']} | "
                    f"{item['risk_label']} | {item.get('status', 'Reported')} | "
                    f"{item['submitted_at_str']}"
                ): item
                for item in sorted(filtered, key=lambda x: x["submitted_at"], reverse=True)
            }

            selected_label = st.selectbox(
                "Select incident",
                options=list(incident_options.keys()),
            )
            selected_incident = incident_options[selected_label]

            status_col1, status_col2 = st.columns([1.2, 1])
            with status_col1:
                new_status = st.selectbox(
                    "Update status",
                    options=INCIDENT_STATUSES,
                    index=INCIDENT_STATUSES.index(selected_incident.get("status", "Reported")),
                )
            with status_col2:
                if st.button("Apply Status", use_container_width=True):
                    update_submission_status(selected_incident["id"], new_status)
                    st.success(f"Incident #{selected_incident['id']} updated to {new_status}.")
                    st.rerun()

            st.caption("Report to authority export with image, timestamp, GPS, and risk details.")
            csv_bytes = build_incident_csv(selected_incident).encode("utf-8")
            json_bytes = build_incident_json(selected_incident).encode("utf-8")
            pdf_bytes = build_incident_pdf(selected_incident)

            export_col1, export_col2, export_col3 = st.columns(3)
            with export_col1:
                st.download_button(
                    label="Export CSV",
                    data=csv_bytes,
                    file_name=f"incident_{selected_incident['id']}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with export_col2:
                st.download_button(
                    label="Export JSON",
                    data=json_bytes,
                    file_name=f"incident_{selected_incident['id']}.json",
                    mime="application/json",
                    use_container_width=True,
                )
            with export_col3:
                st.download_button(
                    label="Export PDF",
                    data=pdf_bytes,
                    file_name=f"incident_{selected_incident['id']}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        else:
            st.info("Incident workflow is available when at least one filtered incident exists.")

        clear_col, _ = st.columns([1, 4])
        with clear_col:
            if st.button("Clear Dashboard Data", use_container_width=True):
                clear_submissions()
                st.rerun()

    with st.expander("How this prototype works"):
        st.write(
            "This hackathon prototype estimates blockage from image darkness and texture, "
            "then combines it with rainfall intensity and location factor to estimate flood risk."
        )


if __name__ == "__main__":
    main()