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

st.set_page_config(page_title="CastIQ Pro", page_icon="🎣", layout="wide")

st.title("🎣 CastIQ Pro")
st.caption("Stand here. Cast there. Use this bait. Navigate safely. Fish responsibly.")

FEEDBACK_FILE = "feedback_log.csv"

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
    "Bonito", "Spoon lure", "Paddle tail lure", "Small crab", "Crayfish",
    "Fish fillet"
]

def calculate_bearing(start, end):
    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def bearing_to_compass(bearing):
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
    return directions[round(bearing / 45)]

def confidence_label(score):
    if score >= 85: return "Very High"
    if score >= 75: return "High"
    if score >= 60: return "Medium"
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
        0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle",
        53: "Moderate drizzle", 55: "Dense drizzle", 61: "Slight rain",
        63: "Moderate rain", 65: "Heavy rain", 80: "Rain showers",
        81: "Moderate showers", 82: "Violent showers", 95: "Thunderstorm"
    }
    return codes.get(code, "Weather condition")

def wind_direction_text(deg):
    if deg is None: return "Unknown"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
    return dirs[round(deg / 45)]

def moon_phase_name(d):
    # simple approximate lunar phase, good enough for prototype
    known_new_moon = date(2000, 1, 6)
    days = (d - known_new_moon).days
    lunation = 29.53058867
    phase = (days % lunation) / lunation
    if phase < 0.03 or phase > 0.97: return "New Moon"
    if phase < 0.22: return "Waxing Crescent"
    if phase < 0.28: return "First Quarter"
    if phase < 0.47: return "Waxing Gibbous"
    if phase < 0.53: return "Full Moon"
    if phase < 0.72: return "Waning Gibbous"
    if phase < 0.78: return "Last Quarter"
    return "Waning Crescent"

def moon_fishing_effect(phase):
    if phase in ["New Moon", "Full Moon"]:
        return 8, "Stronger tidal movement expected around new/full moon."
    if phase in ["First Quarter", "Last Quarter"]:
        return 3, "Moderate moon influence."
    return 1, "Lower moon-driven tidal influence."

def fetch_conditions(lat, lon, trip_date, bucket):
    target_hour = time_bucket_hour.get(bucket, 12)
    target_date = trip_date.strftime("%Y-%m-%d")

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
            "cloud_cover"
        ]),
        "timezone": "auto",
        "forecast_days": 10
    }

    marine_url = "https://marine-api.open-meteo.com/v1/marine"
    marine_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "wave_height",
            "wave_period",
            "wave_direction",
            "sea_surface_temperature"
        ]),
        "timezone": "auto",
        "forecast_days": 10
    }

    result = {
        "available": False,
        "weather_error": None,
        "marine_error": None
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
    elif tide_stage == "High tide turning" or tide_stage == "Low tide turning":
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
            positives.append("Wind speed is fishable.")
        elif wind <= 40:
            score -= 2
            negatives.append("Wind may make casting and bait control harder.")
        else:
            score -= 10
            negatives.append("Strong wind may be unsafe or difficult.")

    if wave is not None:
        if 0.7 <= wave <= 1.8:
            score += 10
            positives.append("Swell height likely creates working water.")
        elif wave < 0.7:
            score -= 3
            negatives.append("Sea may be too flat with limited working water.")
        else:
            score -= 8
            negatives.append("Swell may be too rough; check safety.")

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
        positives.append("Time bucket suits Kob feeding behaviour.")
    if selected_species == "Shad" and time_bucket in ["Early Morning", "Morning", "Afternoon"]:
        score += 5
        positives.append("Time bucket suits Shad activity.")
    if selected_species == "Garrick" and time_bucket in ["Morning", "Afternoon"]:
        score += 5
        positives.append("Time bucket suits Garrick movement.")

    return max(0, min(95, score)), positives, negatives

fishing_spots = {
    "Leisure Bay Main Beach": {
        "area": "Leisure Bay, South Coast", "stand": (-30.823900, 30.406200),
        "cast": (-30.824250, 30.406650), "structure": "Dark sand gully with white-water edge",
        "feature_type": "gully", "depth_note": "Estimated deeper gully between shallow sandbanks",
        "confidence": 78,
        "species": ["Kob", "Shad", "Bronze Bream", "Blacktail", "Stone Bream", "Sand Shark", "Grey Shark", "Diamond Ray"],
        "notes": "Good beach structure. Fish the edge where white water meets darker channel."
    },
    "Trafalgar Beach": {
        "area": "Trafalgar, South Coast", "stand": (-30.833900, 30.410500),
        "cast": (-30.834300, 30.411050), "structure": "Rock and sand transition with feeding gully",
        "feature_type": "gully", "depth_note": "Medium-depth gully near rock/sand transition",
        "confidence": 82,
        "species": ["Kob", "Shad", "Bronze Bream", "Blacktail", "Stone Bream", "Grey Shark", "Honeycomb Ray", "Diamond Ray"],
        "notes": "Strong structure option. Target the gully edge, not the middle."
    },
    "Palm Beach": {
        "area": "Palm Beach, South Coast", "stand": (-30.867000, 30.382300),
        "cast": (-30.867420, 30.382850), "structure": "Working white water with channel edge",
        "feature_type": "white water", "depth_note": "Working white water over sandbank edge",
        "confidence": 74,
        "species": ["Shad", "Kob", "Garrick", "Bronze Bream", "Blacktail", "Pompano", "Grey Shark"],
        "notes": "Good if water is working. Better for shad when there is visible white water."
    },
    "Southbroom Beach": {
        "area": "Southbroom, South Coast", "stand": (-30.919200, 30.328700),
        "cast": (-30.919650, 30.329300), "structure": "River-mouth influence with deeper channel",
        "feature_type": "river mouth", "depth_note": "Channel edge influenced by river-mouth water movement",
        "confidence": 76,
        "species": ["Kob", "Garrick", "Grunter", "Pompano", "Shad", "Sand Shark", "Grey Shark"],
        "notes": "Better around moving tide. Fish the channel and current seam."
    },
    "Umhlanga Rocks": {
        "area": "Durban North", "stand": (-29.717820, 31.089420),
        "cast": (-29.718050, 31.089880), "structure": "Rock ledge and deep gully",
        "feature_type": "gully", "depth_note": "Rocky gully / deeper channel close to ledge",
        "confidence": 77,
        "species": ["Kob", "Garrick", "Shad", "Blacktail", "Bronze Bream", "Kingfish", "Rockcod"],
        "notes": "Classic rock and gully structure. Use caution on rocks."
    }
}

area_locations = {
    "Leisure Bay": (-30.823900, 30.406200),
    "Trafalgar": (-30.833900, 30.410500),
    "Palm Beach": (-30.867000, 30.382300),
    "Southbroom": (-30.919200, 30.328700),
    "Umhlanga Rocks": (-29.717820, 31.089420),
}

safety_ratings = {
    "Leisure Bay Main Beach": {"risk": "Medium", "advice": "Avoid isolated fishing at night. Prefer daylight or fish with others."},
    "Trafalgar Beach": {"risk": "Medium", "advice": "Use known access points. Avoid leaving valuables visible in your vehicle."},
    "Palm Beach": {"risk": "Medium", "advice": "Be cautious around quiet access points, especially early morning or night."},
    "Southbroom Beach": {"risk": "Low to Medium", "advice": "Generally safer around active areas, but avoid isolated night fishing alone."},
    "Umhlanga Rocks": {"risk": "Medium", "advice": "Busy area, but vehicle break-ins can occur. Park in visible, well-lit areas."}
}

species_engine = {
    "Kob": {
        "ideal_baits": ["Chokka", "Sardine", "Mackerel", "Live mullet", "Fish fillet"],
        "time_bonus": ["Early Morning", "Evening", "Night", "Midnight"],
        "thinking": "Kob prefer deeper gullies, holes and slower water near the bottom.",
        "bait": "Chokka + sardine combo, mackerel fillet, live bait where legal",
        "trace": "Sliding sinker trace", "leader": "0.55mm to 0.70mm nylon leader",
        "hooks": "2 x 5/0 to 7/0 hooks, or circle hooks", "sinker": "5oz to 6oz grapnel sinker",
        "technique": "Cast into the deep channel. Let bait settle. Slow drag every 30–60 seconds.",
        "bite_style": "Soft pickup → suction feed → slow run",
        "feel": "Light taps, rod slowly loads, fish may feel like dead weight first.",
        "response": "Do not strike immediately. Let the rod load, then lift firmly.",
        "mistake": "Striking too early.", "trace_image": "images/kob_trace.png",
        "bait_image": "images/bait/chokka_sardine_combo_bait.png",
        "trace_diagram": "Main Line\n|\nRunning sinker clip ---- 5oz grapnel\n|\nSwivel\n|\nLeader\n|\nHook 5/0\n|\nHook 5/0"
    },
    "Shad": {
        "ideal_baits": ["Sardine", "Chokka", "Spoon lure"],
        "time_bonus": ["Early Morning", "Morning", "Afternoon", "Evening"],
        "thinking": "Shad are aggressive feeders that like white water and moving bait.",
        "bait": "Sardine, chokka strip, spoon lure",
        "trace": "Short steel trace", "leader": "Light steel trace with 0.45mm nylon leader",
        "hooks": "1/0 to 3/0 hooks", "sinker": "2oz to 4oz sinker depending on surf",
        "technique": "Cast into working white water. Keep bait moving. Retrieve actively.",
        "bite_style": "Fast repeated hits → aggressive attack",
        "feel": "Multiple sharp knocks, fast tapping, bait stripped quickly.",
        "response": "Strike quickly and keep pressure.", "mistake": "Leaving bait too static.",
        "trace_image": "images/shad_trace.png", "bait_image": "images/bait/sardine_bait.png",
        "trace_diagram": "Main Line\n|\nSwivel\n|\nShort steel trace\n|\n1/0 - 3/0 hook\n|\nSardine"
    },
    "Garrick": {
        "ideal_baits": ["Live mullet", "Paddle tail lure", "Spoon lure"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Garrick hunt moving bait in current seams, river mouths and channel edges.",
        "bait": "Live mullet, paddle tail lure, spoon lure",
        "trace": "Live bait trace / light steel leader", "leader": "0.60mm nylon or light steel bite trace",
        "hooks": "Single 6/0 to 8/0 circle hook", "sinker": "Minimal weight or free-swim live bait",
        "technique": "Work live bait naturally along the current seam.",
        "bite_style": "Aggressive grab → fast run",
        "feel": "Sharp pull, line runs quickly, rod tip dips hard.",
        "response": "Keep rod tip up. Let circle hook set under pressure.",
        "mistake": "Striking too hard too early.", "trace_image": "images/garrick_trace.png",
        "bait_image": "images/bait/live_mullet_bait.png",
        "trace_diagram": "Main Line\n|\nSwivel\n|\nLeader\n|\nCircle hook\n|\nLive mullet"
    },
    "Bronze Bream": {
        "ideal_baits": ["Prawn", "Red bait", "Mussel", "Crayfish"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Bronze bream hold close to rocks, reef edges and foamy water.",
        "bait": "Prawn, red bait, mussel, crayfish where legal",
        "trace": "Short scratching trace", "leader": "0.40mm to 0.55mm leader",
        "hooks": "1/0 to 3/0 strong hooks", "sinker": "2oz to 4oz sinker",
        "technique": "Fish closer in around rocks and foamy pockets. Do not overcast.",
        "bite_style": "Small taps → firm pull",
        "feel": "Small pecks, short sharp pulls, then strong movement into rocks.",
        "response": "Lift firmly once committed and keep pressure.",
        "mistake": "Fishing too far out.", "trace_image": "images/bronze_bream_trace.png",
        "bait_image": "images/bait/prawn_bait.png",
        "trace_diagram": "Main Line\n|\nSwivel\n|\nShort leader\n|\nSmall strong hook\n|\nPrawn"
    }
}

# Add simple fallback species by copying Bronze Bream/Kob style
for extra in ["Blacktail", "Stone Bream", "Grunter", "Pompano", "Sand Shark", "Grey Shark", "Diamond Ray", "Honeycomb Ray", "Kingfish", "Rockcod"]:
    if extra not in species_engine:
        base = species_engine["Kob"] if any(x in extra for x in ["Shark", "Ray", "Kingfish", "Rockcod"]) else species_engine["Bronze Bream"]
        species_engine[extra] = base.copy()
        species_engine[extra]["thinking"] = f"{extra} guidance uses prototype rules; refine with local data."
        species_engine[extra]["trace_image"] = f"images/{extra.lower().replace(' ', '_')}_trace.png"

if not os.path.exists("images"):
    os.makedirs("images")

st.sidebar.header("📍 Location")

location_method = st.sidebar.radio("Choose location method", ["Use current GPS", "Enter coordinates", "Choose area name"])

if location_method == "Use current GPS":
    location = streamlit_geolocation()
    if location and location.get("latitude") is not None:
        user_location = (location["latitude"], location["longitude"])
        st.sidebar.success(f"GPS found: {user_location[0]:.6f}, {user_location[1]:.6f}")
    else:
        user_location = (-30.823900, 30.406200)
        st.sidebar.warning("GPS not available. Using Leisure Bay sample.")
elif location_method == "Enter coordinates":
    manual_lat = st.sidebar.number_input("Latitude", value=-30.823900, format="%.6f")
    manual_lon = st.sidebar.number_input("Longitude", value=30.406200, format="%.6f")
    user_location = (manual_lat, manual_lon)
else:
    selected_area = st.sidebar.selectbox("Where will you be fishing from?", list(area_locations.keys()))
    user_location = area_locations[selected_area]

st.header("🎯 Trip Setup")

trip_date = st.date_input("Fishing date", value=datetime.today())

time_bucket = st.selectbox("Preferred fishing time", list(time_bucket_windows.keys()))
st.success(f"Selected time window: {time_bucket_windows[time_bucket]}")

tide_stage = st.selectbox(
    "Tide stage",
    ["Pushing tide", "Outgoing tide", "High tide turning", "Low tide turning", "Slack / not sure"]
)

max_travel_km = st.selectbox("How far are you willing to travel?", [2, 5, 10, 20, 50, 100], index=2)

casting_ability = st.selectbox(
    "Casting ability",
    ["Beginner: 20–40m", "Average: 40–70m", "Strong caster: 70–110m", "Advanced: 110m+"],
    index=1
)

preferred_target = st.selectbox("Preferred target species", ["Auto select"] + list(species_engine.keys()))

available_baits = st.multiselect("Bait you have available - select up to 10", all_baits, max_selections=10)

closest_name = min(fishing_spots, key=lambda x: geodesic(user_location, fishing_spots[x]["stand"]).km)
closest_distance = geodesic(user_location, fishing_spots[closest_name]["stand"]).km

candidates = []
for name, spot_data in fishing_spots.items():
    dist_km = geodesic(user_location, spot_data["stand"]).km
    if dist_km <= max_travel_km:
        score = spot_data["confidence"]
        for fish in spot_data["species"]:
            if fish in species_engine and time_bucket in species_engine[fish]["time_bonus"]:
                score += 4
            if fish in species_engine:
                bait_status_temp, _, _ = bait_match_engine(available_baits, species_engine[fish]["ideal_baits"])
                if bait_status_temp == "Good match":
                    score += 4
        if dist_km <= 5: score += 5
        elif dist_km <= 10: score += 3
        elif dist_km <= 20: score += 1
        candidates.append((name, dist_km, score))

if not candidates:
    candidates.append((closest_name, closest_distance, fishing_spots[closest_name]["confidence"]))

candidates.sort(key=lambda x: x[2], reverse=True)
best_spot_name, best_distance, best_review_score = candidates[0]

spot = fishing_spots[best_spot_name]
stand = spot["stand"]
cast = spot["cast"]
cast_distance = geodesic(stand, cast).meters
bearing = calculate_bearing(stand, cast)
compass = bearing_to_compass(bearing)
likely_species = spot["species"]

if preferred_target == "Auto select":
    ranked = []
    for fish in likely_species:
        if fish not in species_engine: continue
        score = 50
        if time_bucket in species_engine[fish]["time_bonus"]: score += 12
        bait_status_temp, _, _ = bait_match_engine(available_baits, species_engine[fish]["ideal_baits"])
        if bait_status_temp == "Good match": score += 10
        elif bait_status_temp == "Poor match": score -= 8
        ranked.append((fish, score))
    ranked.sort(key=lambda x: x[1], reverse=True)
    selected_species = ranked[0][0]
else:
    selected_species = preferred_target

species = species_engine[selected_species]
bait_status, matched_baits, bait_message = bait_match_engine(available_baits, species["ideal_baits"])

conditions = fetch_conditions(stand[0], stand[1], trip_date, time_bucket)
moon_phase = moon_phase_name(trip_date)
condition_score, cond_pos, cond_neg = condition_score_engine(
    conditions, tide_stage, moon_phase, selected_species, time_bucket
)

confidence = spot["confidence"]
if selected_species in likely_species: confidence += 5
else: confidence -= 8
if time_bucket in species["time_bonus"]:
    confidence += 8
    time_reason = f"{selected_species} is favoured during {time_bucket}."
else:
    confidence -= 3
    time_reason = f"{time_bucket} is not the strongest time for {selected_species}."
if bait_status == "Good match": confidence += 5
elif bait_status == "Poor match": confidence -= 10
confidence = int((confidence * 0.65) + (condition_score * 0.35))
confidence = max(0, min(95, confidence))

st.divider()

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("🎯 Best Fishing Recommendation")
    st.metric("My best recommendation", best_spot_name)
    st.write(f"**Distance from selected/current location:** {best_distance:.2f} km")
    st.write(f"**Initial closest spot:** {closest_name} ({closest_distance:.2f} km)")
    st.write(f"**Trip time:** {time_bucket} ({time_bucket_windows[time_bucket]})")
    st.write(f"**Structure:** {spot['structure']}")
    st.write(f"**Why this spot:** {spot['notes']}")

with col2:
    st.subheader("📊 Recommendation Score")
    st.metric("Fishing confidence", f"{confidence}%")
    st.write(f"**Level:** {confidence_label(confidence)}")
    st.write(f"**Time logic:** {time_reason}")
    st.write(f"**Bait logic:** {bait_message}")
    st.write(f"**Conditions score:** {condition_score}%")

st.divider()
st.subheader("🌊 Fishing Conditions Summary")

wcol1, wcol2, wcol3 = st.columns(3)

with wcol1:
    st.write("**Weather**")
    if conditions.get("available"):
        st.write(f"Temperature: {conditions.get('temperature')} °C")
        st.write(f"Weather: {weather_code_text(conditions.get('weather_code'))}")
        st.write(f"Rain probability: {conditions.get('rain_probability')}%")
        st.write(f"Pressure: {conditions.get('pressure')} hPa")
        st.write(f"Cloud cover: {conditions.get('cloud_cover')}%")
    else:
        st.warning("Weather data unavailable.")

with wcol2:
    st.write("**Wind + Marine**")
    st.write(f"Wind: {conditions.get('wind_speed')} km/h from {wind_direction_text(conditions.get('wind_direction'))}")
    st.write(f"Wave height: {conditions.get('wave_height')} m")
    st.write(f"Wave period: {conditions.get('wave_period')} sec")
    st.write(f"Wave direction: {wind_direction_text(conditions.get('wave_direction'))}")
    st.write(f"Sea temperature: {conditions.get('sea_temp')} °C")

with wcol3:
    st.write("**Tide + Moon**")
    st.write(f"Tide stage: {tide_stage}")
    st.write(f"Moon phase: {moon_phase}")
    st.write(f"Conditions score: {condition_score}%")

if cond_pos:
    st.success("Positive signals: " + " | ".join(cond_pos))
if cond_neg:
    st.warning("Caution signals: " + " | ".join(cond_neg))

st.divider()
st.subheader("🛡️ Area Safety Awareness")

safety = safety_ratings.get(best_spot_name, {"risk": "Unknown", "advice": "No safety profile loaded yet."})
if "Medium" in safety["risk"]:
    st.warning(f"Safety risk: {safety['risk']}")
elif "Low" in safety["risk"]:
    st.success(f"Safety risk: {safety['risk']}")
else:
    st.error(f"Safety risk: {safety['risk']}")
st.write(f"**Safety advice:** {safety['advice']}")

st.divider()
st.subheader("🎣 Bait Decision")

st.write(f"**Selected target:** {selected_species}")
st.write(f"**Ideal bait:** {', '.join(species['ideal_baits'])}")
if available_baits:
    st.write(f"**Bait you have:** {', '.join(available_baits)}")
if bait_status == "Good match":
    st.success(f"✅ {bait_message}")
elif bait_status == "Poor match":
    st.warning(f"⚠️ {bait_message}")
else:
    st.info("Select bait above to get bait matching advice.")

bait_image_name = species.get("bait_image", "").split("/")[-1]
bait_image_path = f"images/{bait_image_name}"
st.subheader("🖼️ Finished Bait Presentation")
if bait_image_path and os.path.exists(bait_image_path):
    st.image(bait_image_path, caption=f"{selected_species} bait presentation", use_container_width=True)
else:
    st.info(f"Bait image not loaded yet. Add image here: {bait_image_path}")

st.divider()
st.subheader("📍 Stand Here → Cast There")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stand GPS", f"{stand[0]:.6f}, {stand[1]:.6f}")
c2.metric("Cast GPS", f"{cast[0]:.6f}, {cast[1]:.6f}")
c3.metric("Cast Distance", f"{int(cast_distance)} m")
c4.metric("Direction", f"{int(bearing)}° {compass}")

st.info(f"Stand at the GPS point. Face {int(bearing)}° {compass}. Cast approximately {int(cast_distance)}m into the target structure.")

st.subheader("🛰️ Satellite View: Stand Point → Cast Direction")

map_center = [(stand[0] + cast[0]) / 2, (stand[1] + cast[1]) / 2]
m = folium.Map(location=map_center, zoom_start=17, tiles=None)

folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery",
    name="Satellite",
    overlay=False,
    control=True
).add_to(m)

folium.Marker([user_location[0], user_location[1]], popup="Your selected/current location", tooltip="You / planned location", icon=folium.Icon(color="blue", icon="user")).add_to(m)
folium.Marker([stand[0], stand[1]], popup="Stand here", tooltip="Stand here", icon=folium.Icon(color="green", icon="flag")).add_to(m)
folium.Marker([cast[0], cast[1]], popup=f"Cast target: {int(cast_distance)}m", tooltip="Cast target", icon=folium.Icon(color="red", icon="screenshot")).add_to(m)
folium.PolyLine([[stand[0], stand[1]], [cast[0], cast[1]]], weight=5, opacity=0.9, tooltip=f"Cast {int(cast_distance)}m at {int(bearing)}° {compass}").add_to(m)
folium.Circle([cast[0], cast[1]], radius=15, popup="Estimated bait landing zone / target gully", tooltip="Bait landing zone", fill=True).add_to(m)

st_folium(m, width=1150, height=560)

st.subheader("🧭 Take Me There")
drive_url = f"https://www.google.com/maps/dir/?api=1&destination={stand[0]},{stand[1]}&travelmode=driving"
walk_url = f"https://www.google.com/maps/dir/?api=1&destination={stand[0]},{stand[1]}&travelmode=walking"

n1, n2 = st.columns(2)
with n1:
    st.link_button("🚗 Drive me there", drive_url)
with n2:
    st.link_button("🚶 Walk me there", walk_url)

st.divider()
st.subheader("🎯 Casting Ability Check")

if "Beginner" in casting_ability and cast_distance > 40:
    st.warning("This target may be too far for a beginner.")
elif "Average" in casting_ability and cast_distance > 70:
    st.warning("This cast is at the upper end for an average caster.")
elif "Strong" in casting_ability and cast_distance > 110:
    st.warning("This cast may be beyond strong-caster range.")
else:
    st.success("This casting distance matches your selected ability range.")

st.divider()
st.subheader("🐟 Species Prediction")

for i, fish in enumerate(likely_species, start=1):
    st.write(f"{i}. **{fish}**")

st.subheader(f"🎯 Selected Target: {selected_species}")
st.write(f"**How pros think:** {species['thinking']}")
st.write(f"**Recommended bait:** {species['bait']}")
st.write(f"**Trace:** {species['trace']}")
st.write(f"**Leader:** {species['leader']}")
st.write(f"**Hooks:** {species['hooks']}")
st.write(f"**Sinker:** {species['sinker']}")
st.write(f"**Technique:** {species['technique']}")

st.subheader("🐟 Bite Behaviour")
st.write(f"**Bite style:** {species['bite_style']}")
st.write(f"**What it feels like:** {species['feel']}")
st.write(f"**What you must do:** {species['response']}")
st.warning(f"Common mistake: {species['mistake']}")

st.subheader("🧵 Trace Recommendation")
trace_image_path = species.get("trace_image")
if trace_image_path and os.path.exists(trace_image_path):
    st.image(trace_image_path, caption=f"{selected_species} completed trace setup", use_container_width=True)
else:
    st.info(f"Trace image not loaded yet. Add image here: {trace_image_path}")
    st.code(species["trace_diagram"])

st.divider()
st.subheader("🌱 Responsible Fishing Reminder")

st.warning("""
Because CastIQ Pro may improve catch success, responsible fishing is essential.

✔ Check legal size and bag limits before keeping fish  
✔ Release protected, undersized or breeding fish  
✔ Wet hands before handling fish  
✔ Minimise time out of water  
✔ Use barbless hooks where practical  
✔ Do not fish closed areas or marine protected zones  
✔ Take only what you need  
""")

st.divider()
st.subheader("💬 Feedback / Accuracy Improvement")

with st.form("feedback_form"):
    result = st.selectbox("Did the recommendation work?", ["Not fished yet", "Yes - caught fish", "Had bites only", "No action", "Wrong spot", "Wrong bait", "Wrong trace", "Wrong species"])
    actual_species = st.text_input("What species did you catch or see?")
    actual_bait = st.text_input("What bait worked or failed?")
    catch_outcome = st.selectbox("Catch outcome", ["No catch", "Released", "Kept legally", "Unsure"])
    comments = st.text_area("Your suggestion / improvement")
    submitted = st.form_submit_button("Submit Feedback")

    if submitted:
        feedback = {
            "timestamp": datetime.now().isoformat(),
            "user_lat": user_location[0],
            "user_lon": user_location[1],
            "trip_date": str(trip_date),
            "time_bucket": time_bucket,
            "tide_stage": tide_stage,
            "condition_score": condition_score,
            "travel_range_km": max_travel_km,
            "recommended_best_spot": best_spot_name,
            "target_species": selected_species,
            "available_baits": ", ".join(available_baits),
            "recommended_bait": species["bait"],
            "bait_status": bait_status,
            "result": result,
            "actual_species": actual_species,
            "actual_bait": actual_bait,
            "catch_outcome": catch_outcome,
            "comments": comments,
            "confidence": confidence,
            "cast_distance_m": int(cast_distance),
            "bearing": int(bearing),
        }
        df = pd.DataFrame([feedback])
        try:
            existing = pd.read_csv(FEEDBACK_FILE)
            df = pd.concat([existing, df], ignore_index=True)
        except FileNotFoundError:
            pass
        df.to_csv(FEEDBACK_FILE, index=False)
        st.success("Feedback saved. This will improve future recommendations.")

st.divider()
st.caption("Prototype only. Always verify local regulations, conditions, access rights and safety before fishing.")
