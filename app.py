import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import plotly.express as px
import os
import re
from urllib.parse import parse_qs, urlparse

DATE_TIME = "date/time"
LOCAL_COLLISIONS_CSV = "./Motor_Vehicle_Collisions_Crashes.csv"


def _normalize_csv_url(url):
    """Convert supported share links (e.g. Google Drive) to direct CSV URLs."""
    if not url:
        return url

    parsed = urlparse(url)
    if "drive.google.com" not in parsed.netloc:
        return url

    query_params = parse_qs(parsed.query)
    file_id = query_params.get("id", [None])[0]

    if not file_id:
        match = re.search(r"/file/d/([^/]+)", parsed.path)
        if match:
            file_id = match.group(1)

    if not file_id:
        return url

    return f"https://drive.google.com/uc?export=download&id={file_id}"


def _get_collisions_source():
    """Resolve CSV source: local file first, then Streamlit secrets/env URL."""
    if os.path.exists(LOCAL_COLLISIONS_CSV):
        return LOCAL_COLLISIONS_CSV

    # Streamlit Cloud supports secrets.toml for private runtime configuration.
    if "COLLISIONS_CSV_URL" in st.secrets:
        return _normalize_csv_url(st.secrets["COLLISIONS_CSV_URL"])

    env_url = os.getenv("COLLISIONS_CSV_URL")
    if env_url:
        return _normalize_csv_url(env_url)

    return None

st.set_page_config(
    page_title="NYC Collision Intelligence Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Manrope', sans-serif;
    }

    .main {
        background: linear-gradient(180deg, #f8fafc 0%, #eef4ff 100%);
    }

    .hero {
        background: linear-gradient(120deg, #0f172a 0%, #1d4ed8 100%);
        border-radius: 16px;
        padding: 1.2rem 1.4rem;
        color: #ffffff;
        margin-bottom: 1rem;
    }

    .kpi-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 0.75rem 1rem;
        box-shadow: 0 1px 4px rgba(15, 23, 42, 0.06);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_data(nrows):
    data_source = _get_collisions_source()
    if not data_source:
        raise FileNotFoundError(
            "CSV data source not found. Provide local file 'Motor_Vehicle_Collisions_Crashes.csv' "
            "or set COLLISIONS_CSV_URL in Streamlit secrets/environment."
        )

    data = pd.read_csv(data_source, nrows=nrows)
    data[DATE_TIME] = pd.to_datetime(
        data["CRASH_DATE"].astype(str) + " " + data["CRASH_TIME"].astype(str),
        errors="coerce",
    )
    data.dropna(subset=['LATITUDE', 'LONGITUDE'], inplace=True)
    data.dropna(subset=[DATE_TIME], inplace=True)
    lowercase = lambda x: str(x).lower()
    data.rename(lowercase, axis="columns", inplace=True)
    return data

try:
    all_data = load_data(15000)
except Exception as err:
    st.error(f"Failed to load collision data: {err}")
    st.info(
        "For Streamlit Cloud deployments, set a direct CSV URL in secrets as COLLISIONS_CSV_URL."
    )
    st.stop()

if all_data.empty:
    st.error("No data was loaded. Please check the CSV file path and structure.")
    st.stop()

st.markdown(
    """
    <div class="hero">
        <h2 style="margin:0;">NYC Collision Intelligence Dashboard</h2>
        <p style="margin:0.35rem 0 0 0;opacity:0.92;">A streamlined view of where and when collisions happen, who is most affected, and what factors contribute most.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.title("Dashboard Controls")
st.sidebar.caption("Use filters to tailor all visualizations.")

borough_options = sorted(all_data["borough"].dropna().unique().tolist())
selected_boroughs = st.sidebar.multiselect(
    "Borough",
    options=borough_options,
    default=borough_options,
)

min_date = all_data[DATE_TIME].dt.date.min()
max_date = all_data[DATE_TIME].dt.date.max()
selected_date_range = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)
if isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
    start_date, end_date = selected_date_range
else:
    start_date = selected_date_range
    end_date = selected_date_range

hour = st.sidebar.slider("Hour to analyze", 0, 23, 8)
injured_people = st.sidebar.slider("Minimum injured persons", 0, 19, 1)
show_raw_data = st.sidebar.checkbox("Show filtered raw data", False)

filtered_data = all_data.copy()
if selected_boroughs:
    filtered_data = filtered_data[filtered_data["borough"].isin(selected_boroughs)]
filtered_data = filtered_data[
    (filtered_data[DATE_TIME].dt.date >= start_date)
    & (filtered_data[DATE_TIME].dt.date <= end_date)
]

hour_data = filtered_data[filtered_data[DATE_TIME].dt.hour == hour]
map_data = filtered_data.query("injured_persons >= @injured_people")[["latitude", "longitude"]].dropna(how="any")

total_collisions = int(len(filtered_data))
total_injured = int(filtered_data["injured_persons"].fillna(0).sum())
total_killed = int(filtered_data["killed_persons"].fillna(0).sum())
unique_days = max(filtered_data[DATE_TIME].dt.date.nunique(), 1)
avg_daily = round(total_collisions / unique_days, 1)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Collisions", f"{total_collisions:,}")
k2.metric("People Injured", f"{total_injured:,}")
k3.metric("People Killed", f"{total_killed:,}")
k4.metric("Avg Collisions / Day", f"{avg_daily}")

tab1, tab2, tab3 = st.tabs(["Geospatial View", "Time Patterns", "Risk & Causes"])

with tab1:
    st.subheader("Collision density and injury hotspots")
    left, right = st.columns([1, 1])
    with left:
        st.caption("Locations with injuries above selected threshold")
        if map_data.empty:
            st.info("No records match the injury threshold and filters.")
        else:
            st.map(map_data)
    with right:
        st.caption("Collision intensity during selected hour")
        if hour_data.empty:
            st.info("No collisions recorded for this hour and filter selection.")
        else:
            midpoint = (hour_data["latitude"].mean(), hour_data["longitude"].mean())
            st.pydeck_chart(
                pdk.Deck(
                    map_style="mapbox://styles/mapbox/light-v11",
                    initial_view_state={
                        "latitude": midpoint[0],
                        "longitude": midpoint[1],
                        "zoom": 10.7,
                        "pitch": 45,
                    },
                    layers=[
                        pdk.Layer(
                            "HexagonLayer",
                            data=hour_data[[DATE_TIME, "latitude", "longitude"]],
                            get_position=["longitude", "latitude"],
                            auto_highlight=True,
                            radius=120,
                            extruded=True,
                            pickable=True,
                            elevation_scale=4,
                            elevation_range=[0, 1500],
                        )
                    ],
                )
            )

with tab2:
    st.subheader("Collision timing analysis")
    if hour_data.empty:
        st.info("No data available for minute-by-minute breakdown in this hour.")
    else:
        hist = np.histogram(hour_data[DATE_TIME].dt.minute, bins=60, range=(0, 60))[0]
        minute_chart_data = pd.DataFrame({"minute": range(60), "crashes": hist})
        fig_minute = px.bar(
            minute_chart_data,
            x="minute",
            y="crashes",
            title=f"Minute-wise collisions between {hour:02d}:00 and {(hour + 1) % 24:02d}:00",
            color="crashes",
            color_continuous_scale="Blues",
        )
        fig_minute.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig_minute, use_container_width=True)

    daily_collisions = (
        filtered_data.set_index(DATE_TIME)
        .resample("D")
        .size()
        .reset_index(name="collisions")
    )
    fig_daily = px.line(
        daily_collisions,
        x=DATE_TIME,
        y="collisions",
        title="Daily collision trend",
        markers=True,
    )
    st.plotly_chart(fig_daily, use_container_width=True)

    weekday_order = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    hourly_heatmap = (
        filtered_data.assign(
            hour=filtered_data[DATE_TIME].dt.hour,
            weekday=filtered_data[DATE_TIME].dt.day_name(),
        )
        .groupby(["weekday", "hour"])
        .size()
        .reset_index(name="collisions")
    )
    fig_heatmap = px.density_heatmap(
        hourly_heatmap,
        x="hour",
        y="weekday",
        z="collisions",
        category_orders={"weekday": weekday_order},
        title="Collision intensity by weekday and hour",
        color_continuous_scale="Teal",
    )
    st.plotly_chart(fig_heatmap, use_container_width=True)

with tab3:
    st.subheader("Road user impact and contributing factors")

    segment = st.selectbox("Affected class", ["Pedestrians", "Cyclists", "Motorists"])
    if segment == "Pedestrians":
        top_streets = (
            filtered_data.query("injured_pedestrians >= 1")
            [["on_street_name", "injured_pedestrians"]]
            .sort_values(by=["injured_pedestrians"], ascending=False)
            .dropna(how="any")
            .head(5)
        )
    elif segment == "Cyclists":
        top_streets = (
            filtered_data.query("injured_cyclists >= 1")
            [["on_street_name", "injured_cyclists"]]
            .sort_values(by=["injured_cyclists"], ascending=False)
            .dropna(how="any")
            .head(5)
        )
    else:
        top_streets = (
            filtered_data.query("injured_motorists >= 1")
            [["on_street_name", "injured_motorists"]]
            .sort_values(by=["injured_motorists"], ascending=False)
            .dropna(how="any")
            .head(5)
        )

    st.write("Top 5 streets by selected affected class")
    st.dataframe(top_streets, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        borough_counts = (
            filtered_data["borough"]
            .fillna("Unknown")
            .value_counts()
            .reset_index()
        )
        borough_counts.columns = ["borough", "collisions"]
        fig_borough = px.bar(
            borough_counts,
            x="borough",
            y="collisions",
            color="collisions",
            title="Collisions by borough",
            color_continuous_scale="Mint",
        )
        fig_borough.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig_borough, use_container_width=True)

    with col_b:
        factor_counts = (
            filtered_data["contributing_factor_vehicle_1"]
            .fillna("Unspecified")
            .replace("", "Unspecified")
            .value_counts()
            .head(10)
            .reset_index()
        )
        factor_counts.columns = ["factor", "collisions"]
        fig_factors = px.bar(
            factor_counts,
            x="collisions",
            y="factor",
            orientation="h",
            title="Top 10 contributing factors",
            color="collisions",
            color_continuous_scale="Sunset",
        )
        fig_factors.update_layout(
            yaxis={"categoryorder": "total ascending"},
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig_factors, use_container_width=True)

if show_raw_data:
    st.subheader("Filtered raw data")
    st.dataframe(filtered_data, use_container_width=True)
