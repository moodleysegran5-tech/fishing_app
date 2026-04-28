import streamlit as st
from streamlit_geolocation import streamlit_geolocation
from geopy.distance import geodesic
import math
import pandas as pd
from datetime import datetime, date
import folium
from streamlit_folium import st_folium
import os
import requests

# =====================================================
# PAGE SETUP
# =====================================================

st.set_page_config(
    page_title="CastIQ Pro",
    page_icon="🎣",
    layout="wide"
)

st.title("🎣 CastIQ Pro")
st.caption("AI Fishing Intelligence: where to stand, where to cast, what bait to use.")

FEEDBACK_FILE = "feedback_log.csv"

# =====================================================
# GLOBAL OPTIONS
# =====================================================

time_bucket_windows = {
    "Early Morning": "04:30 – 07:30",
    "Morning": "07:30 – 10:30",
    "Midday": "10:30 – 14:30",
    "Afternoon": "14:30 – 17:00",
    "Evening": "17:00 – 20:00",
    "Night": "20:00 – 23:59",
    "Midnight": "00:00 – 04:30",
}

time_bucket_hour = {
    "Early Morning": 6,
    "Morning": 9,
    "Midday": 12,
    "Afternoon": 15,
    "Evening": 18,
    "Night": 21,
    "Midnight": 2,
}

all_baits = [
    "Sardine", "Chokka", "Mackerel", "Red bait", "Prawn", "Mussel",
    "Cracker shrimp", "Worm", "Live mullet", "Fish head", "Octopus",
    "Bonito", "Spoon lure", "Paddle tail lure", "Small crab",
    "Crayfish", "Fish fillet"
]

bait_image_lookup = {
    "Sardine": "images/sardine_bait.png",
    "Chokka": "images/chokka_bait.png",
    "Prawn": "images/prawn_bait.png",
    "Mackerel": "images/mackerel_bait.png",
    "Live mullet": "images/live_mullet_bait.png",
    "Fish head": "images/fish_head_bait.png",
    "Octopus": "images/octopus_bait.png",
    "Mussel": "images/mussel_bait.png",
    "Red bait": "images/red_bait.png",
    "Cracker shrimp": "images/cracker_shrimp_bait.png",
    "Worm": "images/worm_bait.png",
    "Spoon lure": "images/spoon_lure_bait.png",
    "Paddle tail lure": "images/paddle_tail_lure_bait.png",
    "Small crab": "images/small_crab_bait.png",
    "Crayfish": "images/crayfish_bait.png",
    "Fish fillet": "images/fish_fillet_bait.png",
    "Bonito": "images/bonito_bait.png",
}

area_locations = {
    "Leisure Bay": (-30.823900, 30.406200),
    "Trafalgar": (-30.833900, 30.410500),
    "Palm Beach": (-30.867000, 30.382300),
    "Southbroom": (-30.919200, 30.328700),
    "Umhlanga Rocks": (-29.717820, 31.089420),
}

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def calculate_bearing(start, end):
    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)
    dlon = lon2 - lon1

    x = math.sin(dlon) * math.cos(lat2)
    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )

    return (math.degrees(math.atan2(x, y)) + 360) % 360


def bearing_to_compass(bearing):
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
    return directions[round(bearing / 45)]


def confidence_label(score):
    if score >= 85:
        return "Very High"
    if score >= 75:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"


def bait_match_engine(available_baits, ideal_baits):
    if not available_baits:
        return "No bait selected", [], "No bait selected. The app will recommend ideal bait only."

    ideal_lower = [x.lower() for x in ideal_baits]
    matched = [bait for bait in available_baits if bait.lower() in ideal_lower]

    if matched:
        return "Good match", matched, f"You have suitable bait: {', '.join(matched)}."

    return "Poor match", [], f"Your bait is not ideal. Best bait: {', '.join(ideal_baits)}."


def weather_code_text(code):
    codes = {
        0: "Clear",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Fog / mist",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        80: "Rain showers",
        81: "Moderate showers",
        82: "Heavy showers",
        95: "Thunderstorm",
    }
    return codes.get(code, "Weather condition")


def direction_text(deg):
    if deg is None:
        return "Unknown"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
    return dirs[round(deg / 45)]


def moon_phase_name(d):
    known_new_moon = date(2000, 1, 6)
    days = (d - known_new_moon).days
    lunation = 29.53058867
    phase = (days % lunation) / lunation

    if phase < 0.03 or phase > 0.97:
        return "New Moon"
    if phase < 0.22:
        return "Waxing Crescent"
    if phase < 0.28:
        return "First Quarter"
    if phase < 0.47:
        return "Waxing Gibbous"
    if phase < 0.53:
        return "Full Moon"
    if phase < 0.72:
        return "Waning Gibbous"
    if phase < 0.78:
        return "Last Quarter"
    return "Waning Crescent"


def moon_fishing_effect(phase):
    if phase in ["New Moon", "Full Moon"]:
        return 8, "New/full moon may increase tidal movement."
    if phase in ["First Quarter", "Last Quarter"]:
        return 3, "Moderate moon influence."
    return 1, "Lower moon-driven tidal influence."


def fetch_conditions(lat, lon, trip_date, bucket):
    target_hour = time_bucket_hour.get(bucket, 12)
    target_date = trip_date.strftime("%Y-%m-%d")

    result = {
        "available": False,
        "weather_error": None,
        "marine_error": None,
    }

    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "temperature_2m",
            "precipitation_probability",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
            "pressure_msl",
            "cloud_cover",
        ]),
        "timezone": "auto",
        "forecast_days": 10,
    }

    marine_url = "https://marine-api.open-meteo.com/v1/marine"
    marine_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "wave_height",
            "wave_period",
            "wave_direction",
            "sea_surface_temperature",
        ]),
        "timezone": "auto",
        "forecast_days": 10,
    }

    try:
        w = requests.get(weather_url, params=weather_params, timeout=10).json()
        times = w.get("hourly", {}).get("time", [])

        idx = None
        for i, t in enumerate(times):
            if t.startswith(target_date) and int(t[11:13]) == target_hour:
                idx = i
                break

        if idx is None and times:
            idx = 0

        if idx is not None:
            h = w["hourly"]
            result.update({
                "available": True,
                "temperature": h.get("temperature_2m", [None])[idx],
                "rain_probability": h.get("precipitation_probability", [None])[idx],
                "weather_code": h.get("weather_code", [None])[idx],
                "wind_speed": h.get("wind_speed_10m", [None])[idx],
                "wind_direction": h.get("wind_direction_10m", [None])[idx],
                "pressure": h.get("pressure_msl", [None])[idx],
                "cloud_cover": h.get("cloud_cover", [None])[idx],
            })

    except Exception as e:
        result["weather_error"] = str(e)

    try:
        m = requests.get(marine_url, params=marine_params, timeout=10).json()
        times = m.get("hourly", {}).get("time", [])

        idx = None
        for i, t in enumerate(times):
            if t.startswith(target_date) and int(t[11:13]) == target_hour:
                idx = i
                break

        if idx is None and times:
            idx = 0

        if idx is not None:
            h = m["hourly"]
            result.update({
                "wave_height": h.get("wave_height", [None])[idx],
                "wave_period": h.get("wave_period", [None])[idx],
                "wave_direction": h.get("wave_direction", [None])[idx],
                "sea_temp": h.get("sea_surface_temperature", [None])[idx],
            })

    except Exception as e:
        result["marine_error"] = str(e)

    return result


def condition_score_engine(conditions, tide_stage, moon_phase, selected_species, time_bucket):
    score = 50
    positives = []
    negatives = []

    wind = conditions.get("wind_speed")
    wave = conditions.get("wave_height")
    period = conditions.get("wave_period")
    rain = conditions.get("rain_probability")

    if tide_stage in ["Pushing tide", "Outgoing tide"]:
        score += 12
        positives.append("Moving tide creates feeding current.")
    elif tide_stage in ["High tide turning", "Low tide turning"]:
        score += 5
        positives.append("Turning tide can trigger short feeding windows.")
    else:
        score -= 4
        negatives.append("Slack/unknown tide reduces confidence.")

    moon_bonus, moon_note = moon_fishing_effect(moon_phase)
    score += moon_bonus
    positives.append(moon_note)

    if wind is not None:
        if wind <= 25:
            score += 8
            positives.append("Wind speed appears fishable.")
        elif wind <= 40:
            score -= 2
            negatives.append("Wind may make casting harder.")
        else:
            score -= 10
            negatives.append("Strong wind may be difficult or unsafe.")

    if wave is not None:
        if 0.7 <= wave <= 1.8:
            score += 10
            positives.append("Swell height may create working water.")
        elif wave < 0.7:
            score -= 3
            negatives.append("Sea may be too flat.")
        else:
            score -= 8
            negatives.append("Swell may be rough; check safety.")

    if period is not None:
        if 8 <= period <= 14:
            score += 5
            positives.append("Wave period supports structured surf movement.")
        elif period > 16:
            score -= 4
            negatives.append("Long-period swell can create powerful sets.")

    if rain is not None and rain >= 70:
        score -= 5
        negatives.append("High rain probability may reduce comfort and visibility.")

    if selected_species == "Kob" and time_bucket in ["Evening", "Night", "Early Morning"]:
        score += 6
        positives.append("Time bucket suits Kob behaviour.")

    if selected_species == "Shad" and time_bucket in ["Early Morning", "Morning", "Afternoon"]:
        score += 5
        positives.append("Time bucket suits Shad activity.")

    if selected_species == "Garrick" and time_bucket in ["Morning", "Afternoon"]:
        score += 5
        positives.append("Time bucket suits Garrick movement.")

    return max(0, min(95, score)), positives, negatives


# =====================================================
# FISHING SPOTS
# =====================================================

fishing_spots = {
    "Leisure Bay Main Beach": {
        "area": "Leisure Bay, South Coast",
        "stand": (-30.823900, 30.406200),
        "cast": (-30.824250, 30.406650),
        "structure": "Dark sand gully with white-water edge",
        "feature_type": "gully",
        "depth_note": "Estimated deeper gully between shallow sandbanks",
        "confidence": 78,
        "species": [
            "Kob", "Shad", "Bronze Bream", "Blacktail",
            "Stone Bream", "Sand Shark", "Grey Shark", "Diamond Ray"
        ],
        "notes": "Good beach structure. Fish the edge where white water meets darker channel.",
    },
    "Trafalgar Beach": {
        "area": "Trafalgar, South Coast",
        "stand": (-30.833900, 30.410500),
        "cast": (-30.834300, 30.411050),
        "structure": "Rock and sand transition with feeding gully",
        "feature_type": "gully",
        "depth_note": "Medium-depth gully near rock/sand transition",
        "confidence": 82,
        "species": [
            "Kob", "Shad", "Bronze Bream", "Blacktail",
            "Stone Bream", "Grey Shark", "Honeycomb Ray", "Diamond Ray"
        ],
        "notes": "Strong structure option. Target the gully edge, not the middle.",
    },
    "Palm Beach": {
        "area": "Palm Beach, South Coast",
        "stand": (-30.867000, 30.382300),
        "cast": (-30.867420, 30.382850),
        "structure": "Working white water with channel edge",
        "feature_type": "white water",
        "depth_note": "Working white water over sandbank edge",
        "confidence": 74,
        "species": [
            "Shad", "Kob", "Garrick", "Bronze Bream",
            "Blacktail", "Pompano", "Grey Shark"
        ],
        "notes": "Good if water is working. Better for Shad when there is visible white water.",
    },
    "Southbroom Beach": {
        "area": "Southbroom, South Coast",
        "stand": (-30.919200, 30.328700),
        "cast": (-30.919650, 30.329300),
        "structure": "River-mouth influence with deeper channel",
        "feature_type": "river mouth",
        "depth_note": "Channel edge influenced by river-mouth water movement",
        "confidence": 76,
        "species": [
            "Kob", "Garrick", "Grunter", "Pompano",
            "Shad", "Sand Shark", "Grey Shark"
        ],
        "notes": "Better around moving tide. Fish the channel and current seam.",
    },
    "Umhlanga Rocks": {
        "area": "Durban North",
        "stand": (-29.717820, 31.089420),
        "cast": (-29.718050, 31.089880),
        "structure": "Rock ledge and deep gully",
        "feature_type": "gully",
        "depth_note": "Rocky gully / deeper channel close to ledge",
        "confidence": 77,
        "species": [
            "Kob", "Garrick", "Shad", "Blacktail",
            "Bronze Bream", "Kingfish", "Rockcod"
        ],
        "notes": "Classic rock and gully structure. Use caution on rocks.",
    },
}


# =====================================================
# SAFETY RATINGS
# =====================================================

safety_ratings = {
    "Leisure Bay Main Beach": {
        "risk": "Medium",
        "advice": "Avoid isolated fishing at night. Prefer daylight or fish with others. Keep valuables out of sight.",
    },
    "Trafalgar Beach": {
        "risk": "Medium",
        "advice": "Use known access points. Avoid leaving valuables visible in your vehicle. Be cautious early morning and night.",
    },
    "Palm Beach": {
        "risk": "Medium",
        "advice": "Be cautious around quiet beach access points, especially early morning or night.",
    },
    "Southbroom Beach": {
        "risk": "Low to Medium",
        "advice": "Generally safer around active areas, but avoid isolated night fishing alone. Park in visible areas.",
    },
    "Umhlanga Rocks": {
        "risk": "Medium",
        "advice": "Busy area, but vehicle break-ins can occur. Park in visible, well-lit areas and avoid isolated rocks at night.",
    },
}


# =====================================================
# SPECIES ENGINE
# =====================================================

species_engine = {
    "Kob": {
        "ideal_baits": ["Chokka", "Sardine", "Mackerel", "Live mullet", "Fish fillet"],
        "time_bonus": ["Early Morning", "Evening", "Night", "Midnight"],
        "thinking": "Kob prefer deeper gullies, holes and slower water near the bottom.",
        "bait": "Chokka + sardine combo, mackerel fillet, live bait where legal.",
        "trace": "Sliding sinker trace",
        "leader": "0.55mm to 0.70mm nylon leader",
        "hooks": "2 x 5/0 to 7/0 hooks, or circle hooks",
        "sinker": "5oz to 6oz grapnel sinker",
        "technique": "Cast into the deep channel. Let bait settle. Slow drag every 30–60 seconds.",
        "bite_style": "Soft pickup → suction feed → slow run",
        "feel": "Light taps, rod slowly loads, fish may feel like dead weight first.",
        "response": "Do not strike immediately. Let the rod load, then lift firmly.",
        "mistake": "Striking too early.",
        "trace_image": "images/kob_trace.png",
        "bait_image": "images/chokka_sardine_combo_bait.png",
        "trace_diagram": "Main Line\n|\nRunning sinker clip ---- 5oz grapnel\n|\nSwivel\n|\nLeader\n|\nHook 5/0\n|\nHook 5/0",
    },
    "Shad": {
        "ideal_baits": ["Sardine", "Chokka", "Spoon lure"],
        "time_bonus": ["Early Morning", "Morning", "Afternoon", "Evening"],
        "thinking": "Shad are aggressive feeders that like white water and moving bait.",
        "bait": "Sardine, chokka strip, spoon lure.",
        "trace": "Short steel trace",
        "leader": "Light steel trace with 0.45mm nylon leader",
        "hooks": "1/0 to 3/0 hooks",
        "sinker": "2oz to 4oz sinker depending on surf",
        "technique": "Cast into working white water. Keep bait moving. Retrieve actively.",
        "bite_style": "Fast repeated hits → aggressive attack",
        "feel": "Multiple sharp knocks, fast tapping, bait stripped quickly.",
        "response": "Strike quickly and keep pressure.",
        "mistake": "Leaving bait too static.",
        "trace_image": "images/shad_trace.png",
        "bait_image": "images/sardine_bait.png",
        "trace_diagram": "Main Line\n|\nSwivel\n|\nShort steel trace\n|\n1/0 - 3/0 hook\n|\nSardine / spoon / chokka strip",
    },
    "Garrick": {
        "ideal_baits": ["Live mullet", "Paddle tail lure", "Spoon lure"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Garrick hunt moving bait in current seams, river mouths and channel edges.",
        "bait": "Live mullet, paddle tail lure, spoon lure.",
        "trace": "Live bait trace / light steel leader",
        "leader": "0.60mm nylon or light steel bite trace",
        "hooks": "Single 6/0 to 8/0 circle hook",
        "sinker": "Minimal weight or free-swim live bait",
        "technique": "Work live bait naturally along the current seam.",
        "bite_style": "Aggressive grab → fast run",
        "feel": "Sharp pull, line runs quickly, rod tip dips hard.",
        "response": "Keep rod tip up. Let circle hook set under pressure.",
        "mistake": "Striking too hard too early.",
        "trace_image": "images/garrick_trace.png",
        "bait_image": "images/live_mullet_bait.png",
        "trace_diagram": "Main Line\n|\nSwivel\n|\nLeader / light steel\n|\nSingle 6/0 - 8/0 circle hook\n|\nLive mullet",
    },

}

# =====================================================
# REGULATION ENGINE
# =====================================================

regulation_table = pd.DataFrame([
    ["Blacktail", "5", "20 cm", "Open", "No", "Check area", "Warn if >5"],
    ["Bronze Bream", "2", "30 cm", "Open", "No", "Check area", "Warn if >2"],
    ["Shad", "4", "30 cm", "Seasonal closure", "No", "Check area", "Block in closure"],
    ["Kob", "Varies", "60 cm", "Open", "No", "Check area", "Ask catch method"],
    ["Garrick", "2", "70 cm", "Seasonal", "No", "Check area", "Warn limits"],
    ["Pompano", "5", "No limit", "Open", "No", "Check area", "Log size"],
], columns=[
    "Fish",
    "Bag Limit",
    "Min Size",
    "Closed Season",
    "Protected",
    "MPA Check",
    "Feedback Rule"
])

# =====================================================
# TABS
# =====================================================

tabs = st.tabs([
    "🏠 Home",
    "🎯 Recommendation",
    "🛰️ Map",
    "🎣 Bait & Trace",
    "🌊 Conditions",
    "🛡️ Safety",
    "📏 Regulations",
    "💎 Packages",
    "📘 Guide",
    "❓ FAQ"
])

# =====================================================
# HOME TAB
# =====================================================

with tabs[0]:
    st.markdown("""
    # 🎣 CastIQ Pro

    ### More fishing. Less guessing.

    Every angler knows the feeling.

    You wake up early, pack the rods, buy bait, drive to the coast, walk the beach, scan the water…  
    and still spend hours wondering:

    **Am I standing in the right place?**  
    **Am I casting into the right water?**  
    **Am I using the right bait for what is actually feeding here?**

    Fishing time is limited.  
    Bait costs money.  
    Fuel costs money.  
    And too many sessions become trial and error.

    **CastIQ Pro was built to shift the odds in your favour.**

    It combines location, structure, bait, species behaviour, weather, wind, swell, tide, moon phase and safety logic to give you a more informed fishing decision before you cast.
    """)

    st.divider()

    st.markdown("## Make better decisions before you cast")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("### 📍 **WHERE to stand**")
        st.caption("GPS-guided positioning")
        st.write("Identify the exact stand point based on structure, depth and fish behaviour.")

    with c2:
        st.markdown("### 🎯 **WHERE to cast**")
        st.caption("Direction + distance")
        st.write("Know the exact direction and distance to target feeding zones.")

    with c3:
        st.markdown("### 🎣 **WHAT bait to use**")
        st.caption("Matched to species")
        st.write("Use the right bait based on what is feeding in that structure.")

    st.divider()

    st.subheader("How CastIQ helps")

    st.markdown("""
    ✅ Finds the best spot within your travel range  
    ✅ Shows stand point and cast target  
    ✅ Suggests bait and trace setup  
    ✅ Shows finished bait presentation  
    ✅ Reviews wind, weather, swell, tide and moon  
    ✅ Adds safety and responsible fishing prompts  
    ✅ Learns from your feedback over time  
    """)

    st.info(
        "Start in the 🎯 Recommendation tab. Select your area, travel distance, time, target species and bait. "
        "CastIQ will then build your fishing plan."
    )

    st.warning(
        "CastIQ does not guarantee fish. It is designed to reduce guesswork and improve your decision-making."
    )

# =====================================================
# USER INPUT
# =====================================================

with tabs[1]:

    st.header("Fishing Setup")

    location_mode = st.selectbox("Select location method", ["Area name", "GPS"])

    if location_mode == "Area name":
        selected_area = st.selectbox("Choose area", list(area_locations.keys()))
        current_location = area_locations[selected_area]
    else:
        loc = streamlit_geolocation()
        if loc and loc["latitude"]:
            current_location = (loc["latitude"], loc["longitude"])
        else:
            st.warning("Waiting for GPS...")
            current_location = None

    max_distance = st.slider("Travel radius (km)", 1, 20, 5)
    time_bucket = st.selectbox("Fishing time", list(time_bucket_windows.keys()))
    available_baits = st.multiselect("Select bait you have", all_baits)

    selected_species = st.selectbox("Target species", list(species_engine.keys()))

    if current_location:

        best_spot = None
        best_score = 0

        for name, spot in fishing_spots.items():
            dist = geodesic(current_location, spot["stand"]).km

            if dist <= max_distance:
                score = spot["confidence"]

                if selected_species in spot["species"]:
                    score += 15

                if score > best_score:
                    best_score = score
                    best_spot = (name, spot, dist)

        if best_spot:
            name, spot, dist = best_spot

            st.success(f"Best Spot: {name}")
            st.write(f"Distance: {round(dist,1)} km")

            stand = spot["stand"]
            cast = spot["cast"]

            bearing = calculate_bearing(stand, cast)
            compass = bearing_to_compass(bearing)
            distance = int(geodesic(stand, cast).meters)

            st.markdown(f"""
            **Stand:** {stand}  
            **Cast:** {cast}  
            **Direction:** {int(bearing)}° {compass}  
            **Distance:** {distance} m  
            """)

            species = species_engine[selected_species]

            match_type, matched, bait_msg = bait_match_engine(
                available_baits,
                species["ideal_baits"]
            )

            st.info(bait_msg)

            st.session_state["spot"] = best_spot
            st.session_state["species"] = selected_species
            st.session_state["available_baits"] = available_baits

# =====================================================
# MAP TAB
# =====================================================

with tabs[2]:
    st.header("Map")

    if "spot" in st.session_state:
        name, spot, _ = st.session_state["spot"]

        m = folium.Map(location=spot["stand"], zoom_start=16)

        folium.Marker(spot["stand"], tooltip="Stand").add_to(m)
        folium.Marker(spot["cast"], tooltip="Cast").add_to(m)

        folium.PolyLine([spot["stand"], spot["cast"]]).add_to(m)

        st_folium(m, width=700)

        lat, lon = spot["stand"]

        st.link_button("Open in Google Maps",
            f"https://www.google.com/maps?q={lat},{lon}")

# =====================================================
# BAIT TAB
# =====================================================

with tabs[3]:
    st.header("Bait & Trace")

    if "species" in st.session_state:
        species = species_engine[st.session_state["species"]]
        available_baits = st.session_state["available_baits"]

        matched_image = None

        for bait in available_baits:
            if bait in species["ideal_baits"]:
                matched_image = bait_image_lookup.get(bait)
                break

        if matched_image:
            img_path = matched_image
        else:
            bait_image_name = species.get("bait_image", "").split("/")[-1]
            img_path = f"images/{bait_image_name}"

        st.subheader("Bait Presentation")

        if os.path.exists(img_path):
            st.image(img_path)
        else:
            st.warning(f"Missing image: {img_path}")

        st.subheader("Trace Setup")
        st.code(species["trace_diagram"])

# =====================================================
# CONDITIONS TAB
# =====================================================

with tabs[4]:
    st.header("Conditions")

    if "spot" in st.session_state:
        _, spot, _ = st.session_state["spot"]

        today = datetime.now().date()

        conditions = fetch_conditions(
            spot["stand"][0],
            spot["stand"][1],
            today,
            time_bucket
        )

        moon = moon_phase_name(today)

        score, pos, neg = condition_score_engine(
            conditions,
            "Pushing tide",
            moon,
            st.session_state["species"],
            time_bucket
        )

        st.metric("Conditions Score", score)

        st.write("Moon:", moon)

        for p in pos:
            st.success(p)

        for n in neg:
            st.warning(n)

# =====================================================
# SAFETY TAB
# =====================================================

with tabs[5]:
    st.header("Safety")

    if "spot" in st.session_state:
        name, _, _ = st.session_state["spot"]
        safety = safety_ratings.get(name, {})

        st.write("Risk:", safety.get("risk"))
        st.write(safety.get("advice"))

# =====================================================
# REGULATIONS TAB
# =====================================================

with tabs[6]:
    st.header("Fishing Regulations")

    st.dataframe(regulation_table)

# =====================================================
# PACKAGES TAB
# =====================================================

with tabs[7]:
    st.header("Packages")

    st.subheader("Free")
    st.video("https://www.youtube.com/watch?v=REPLACE_FREE")

    st.subheader("Pro")
    st.video("https://www.youtube.com/watch?v=REPLACE_PRO")

    st.subheader("Elite")
    st.video("https://www.youtube.com/watch?v=REPLACE_ELITE")

# =====================================================
# GUIDE TAB
# =====================================================

with tabs[8]:
    st.header("User Guide")

    st.markdown("""
    1. Select your location  
    2. Choose bait  
    3. Review recommendation  
    4. Navigate to spot  
    5. Fish responsibly  
    """)

# =====================================================
# FAQ TAB
# =====================================================

with tabs[9]:
    st.header("FAQ")

    st.markdown("""
    **How accurate is this app?**  
    Based on structure + conditions logic.

    **Does it guarantee fish?**  
    No — improves probability.

    **Why bait selection matters?**  
    Fish behaviour depends on bait.
    """)
