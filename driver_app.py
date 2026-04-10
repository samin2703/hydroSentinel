from __future__ import annotations

from datetime import datetime

import folium
import streamlit as st
from PIL import Image
from streamlit_folium import st_folium

from core.cv_model import analyze_blockage
from core.risk_engine import calculate_risk, calculate_short_term_probability
from core.storage import init_submissions_db, insert_submission
from core.weather import get_open_meteo_rainfall
from utils.map_utils import (
    derive_geo_factors,
    get_area_center,
    get_location_options,
    get_nearest_area,
)


st.set_page_config(
    page_title="HydroSentinel Driver",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("HydroSentinel Driver")
st.caption("Simple route suggestions based on live rainfall")

init_submissions_db()


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
                max-width: 1200px;
                padding-top: 1.2rem;
                padding-bottom: 2rem;
            }

            h1, h2, h3 {
                color: var(--hs-text);
            }

            .stCaption {
                color: var(--hs-muted) !important;
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
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_professional_theme()


def rain_band(rain_mm: float) -> tuple[str, str]:
    if rain_mm >= 20:
        return "High Rain", "Avoid if possible"
    if rain_mm >= 10:
        return "Moderate Rain", "Drive with caution"
    return "Low Rain", "Route looks safer"


def get_weather_snapshot(area_name: str) -> dict:
    lat, lon = get_area_center(area_name)
    weather = get_open_meteo_rainfall(lat, lon)
    if not weather.get("ok"):
        return {
            "ok": False,
            "area": area_name,
            "lat": lat,
            "lon": lon,
            "rain_next_1h_mm": 0.0,
            "rain_next_2h_mm": 0.0,
            "message": "Weather unavailable",
        }

    return {
        "ok": True,
        "area": area_name,
        "lat": lat,
        "lon": lon,
        "rain_next_1h_mm": float(weather["rain_next_1h_mm"]),
        "rain_next_2h_mm": float(weather["rain_next_2h_mm"]),
        "message": "Live nowcast",
    }


def suggest_weather_route(start_area: str, destination_area: str) -> dict:
    start_weather = get_weather_snapshot(start_area)
    dest_weather = get_weather_snapshot(destination_area)

    if not dest_weather["ok"]:
        return {
            "ok": False,
            "error": "Could not fetch destination weather.",
        }

    band, advice = rain_band(dest_weather["rain_next_1h_mm"])

    alternatives = []
    for area in get_location_options():
        if area == destination_area:
            continue
        snap = get_weather_snapshot(area)
        if snap["ok"]:
            alternatives.append(snap)

    alternatives.sort(key=lambda x: x["rain_next_1h_mm"])
    top_alternatives = alternatives[:3]

    recommendation = (
        f"Primary route: {start_area} -> {destination_area}. "
        f"Destination rain next 1h: {dest_weather['rain_next_1h_mm']:.1f} mm ({band}). {advice}."
    )

    if top_alternatives and dest_weather["rain_next_1h_mm"] >= 10:
        best = top_alternatives[0]
        recommendation += (
            f" Suggested alternate destination corridor: {best['area']} "
            f"({best['rain_next_1h_mm']:.1f} mm next 1h)."
        )

    return {
        "ok": True,
        "start": start_weather,
        "destination": dest_weather,
        "recommendation": recommendation,
        "alternatives": top_alternatives,
    }


with st.sidebar:
    st.header("Settings")
    mode = st.radio("Mode", ["Navigate", "Report Incident"])


if mode == "Navigate":
    st.subheader("Weather-Based Route Suggestion")
    st.caption("No map routing engine. Advice is based on rain nowcast in selected areas.")

    if "nav_result" not in st.session_state:
        st.session_state.nav_result = None
    if "nav_error" not in st.session_state:
        st.session_state.nav_error = None

    locations = get_location_options()
    col_a, col_b = st.columns(2)
    with col_a:
        start_area = st.selectbox("Start Area", locations, index=0)
    with col_b:
        destination_area = st.selectbox("Destination Area", locations, index=1)

    if st.button("Suggest Route", type="primary", use_container_width=True):
        with st.spinner("Checking rainfall across areas..."):
            result = suggest_weather_route(start_area, destination_area)

        if not result["ok"]:
            st.session_state.nav_error = result["error"]
            st.session_state.nav_result = None
        else:
            st.session_state.nav_result = result
            st.session_state.nav_error = None

    if st.session_state.nav_error:
        st.error(st.session_state.nav_error)

    if st.session_state.nav_result:
        result = st.session_state.nav_result
        dest_rain = result["destination"]["rain_next_1h_mm"]
        if dest_rain >= 20:
            st.error(result["recommendation"])
        elif dest_rain >= 10:
            st.warning(result["recommendation"])
        else:
            st.success(result["recommendation"])

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Start Rain (+1h)", f"{result['start']['rain_next_1h_mm']:.1f} mm")
        with m2:
            st.metric("Destination Rain (+1h)", f"{result['destination']['rain_next_1h_mm']:.1f} mm")
        with m3:
            st.metric("Destination Rain (+2h)", f"{result['destination']['rain_next_2h_mm']:.1f} mm")

        st.markdown("### Lower-Rain Alternatives")
        if result["alternatives"]:
            for alt in result["alternatives"]:
                st.write(
                    f"- {alt['area']}: {alt['rain_next_1h_mm']:.1f} mm next 1h, "
                    f"{alt['rain_next_2h_mm']:.1f} mm next 2h"
                )
        else:
            st.info("No alternative weather data available right now.")

        st.markdown("### Area Weather Map")
        map_center = get_area_center(destination_area)
        route_map = folium.Map(location=map_center, zoom_start=11)

        start_center = get_area_center(result["start"]["area"])
        dest_center = get_area_center(result["destination"]["area"])

        folium.Marker(
            start_center,
            tooltip=f"Start: {result['start']['area']}",
            icon=folium.Icon(color="green", icon="play"),
        ).add_to(route_map)

        dest_color = "red" if dest_rain >= 20 else "orange" if dest_rain >= 10 else "blue"
        folium.Marker(
            dest_center,
            tooltip=f"Destination: {result['destination']['area']}",
            icon=folium.Icon(color=dest_color, icon="flag"),
        ).add_to(route_map)

        for alt in result["alternatives"]:
            folium.CircleMarker(
                [alt["lat"], alt["lon"]],
                radius=8,
                color="blue",
                fill=True,
                fill_opacity=0.7,
                tooltip=f"Alt {alt['area']} ({alt['rain_next_1h_mm']:.1f} mm)",
            ).add_to(route_map)

        folium.PolyLine([start_center, dest_center], color="gray", weight=2).add_to(route_map)
        st_folium(route_map, width=1000, height=450, key="simple_weather_route_map")


elif mode == "Report Incident":
    st.subheader("Report a Blocked/Flooded Area")
    st.caption("Pin the flood location on map, then submit report")

    if "report_pin" not in st.session_state:
        st.session_state.report_pin = None

    default_center = [23.8103, 90.3667]

    map_box = folium.Map(location=default_center, zoom_start=12)
    if st.session_state.report_pin:
        folium.Marker(
            st.session_state.report_pin,
            popup="Flood Location",
            icon=folium.Icon(color="orange", icon="warning-sign"),
        ).add_to(map_box)

    map_data = st_folium(map_box, width=1000, height=450, key="report_pin_map")
    if map_data and map_data.get("last_clicked"):
        clicked = map_data["last_clicked"]
        st.session_state.report_pin = [clicked["lat"], clicked["lng"]]
        st.rerun()

    if st.session_state.report_pin:
        st.success(
            f"Pinned: {st.session_state.report_pin[0]:.5f}, {st.session_state.report_pin[1]:.5f}"
        )

    selected_area = st.selectbox("Nearest Area", get_location_options())
    rainfall_mm = st.slider("Current Rainfall (mm/hr)", min_value=0, max_value=150, value=10)
    blockage_score = st.slider("Blockage Severity", min_value=0, max_value=100, value=50)
    uploaded_image = st.file_uploader("Upload photo (optional)", type=["jpg", "jpeg", "png"])

    if st.button("Submit Report", type="primary", use_container_width=True):
        if st.session_state.report_pin is None:
            st.error("Please pin a location first.")
        else:
            report_lat, report_lon = st.session_state.report_pin
            try:
                if uploaded_image:
                    uploaded_image.seek(0)
                    image = Image.open(uploaded_image).convert("RGB")
                    blockage_result = analyze_blockage(image)
                    blockage_score = blockage_result["blockage_score"]

                weather = get_open_meteo_rainfall(report_lat, report_lon)
                rainfall_for_risk = rainfall_mm
                if weather.get("ok"):
                    rainfall_for_risk = float(weather["rain_next_1h_mm"])

                geo_factors = derive_geo_factors(report_lat, report_lon)
                nearest_area_name, _, _ = get_nearest_area(report_lat, report_lon)

                risk_result = calculate_risk(
                    blockage_score=blockage_score,
                    rainfall_mm_per_hr=rainfall_for_risk,
                    location_factor=geo_factors["location_factor"],
                )

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

                image_bytes = None
                image_name = None
                if uploaded_image:
                    uploaded_image.seek(0)
                    image_bytes = uploaded_image.read()
                    image_name = uploaded_image.name

                record = {
                    "submitted_at": datetime.utcnow().isoformat(),
                    "selected_area": selected_area,
                    "nearest_area": nearest_area_name,
                    "lat": report_lat,
                    "lon": report_lon,
                    "risk_label": risk_result["risk_label"],
                    "risk_score": risk_result["risk_score"],
                    "next_2h_probability": short_term["probability"],
                    "blockage_score": blockage_score,
                    "rainfall_used_mm_hr": rainfall_for_risk,
                    "rainfall_source": "Driver Report",
                    "image_name": image_name,
                    "image_bytes": image_bytes,
                    "status": "Reported",
                }

                incident_id = insert_submission(record)
                st.success(f"Report submitted. ID: {incident_id}")
                st.info(risk_result["message"])
                st.session_state.report_pin = None

            except Exception as exc:
                st.error(f"Failed to submit report: {exc}")


st.markdown("---")
st.caption("HydroSentinel Driver App | Simple weather-based route suggestion")
