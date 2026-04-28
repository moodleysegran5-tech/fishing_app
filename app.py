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
st.caption("AI Fishing Intelligence: WHERE to stand. WHERE to cast. WHAT bait to use.")

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

# =====================================================
# PLANNING AREAS
# These are area anchors. The app then searches detailed fishing spots nearby.
# =====================================================

area_locations = {
    "Leisure Bay": (-30.823900, 30.406200),
    "Trafalgar": (-30.833900, 30.410500),
    "Palm Beach": (-30.867000, 30.382300),
    "Southbroom": (-30.919200, 30.328700),
    "Umhlanga Lighthouse": (-29.717820, 31.089420),
    "Umhlanga Lagoon Mouth": (-29.720500, 31.088000),
    "Bronze Beach": (-29.713900, 31.092000),
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


def direction_text(deg):
    if deg is None:
        return "Unknown"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
    return dirs[round(deg / 45)]


def weather_code_text(code):
    codes = {
        0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Fog / mist", 51: "Light drizzle",
        53: "Moderate drizzle", 55: "Dense drizzle", 61: "Slight rain",
        63: "Moderate rain", 65: "Heavy rain", 80: "Rain showers",
        81: "Moderate showers", 82: "Heavy showers", 95: "Thunderstorm",
    }
    return codes.get(code, "Weather condition")


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

    result = {"available": False, "weather_error": None, "marine_error": None}

    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "temperature_2m", "precipitation_probability", "weather_code",
            "wind_speed_10m", "wind_direction_10m", "pressure_msl", "cloud_cover"
        ]),
        "timezone": "auto",
        "forecast_days": 10,
    }

    marine_url = "https://marine-api.open-meteo.com/v1/marine"
    marine_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "wave_height", "wave_period", "wave_direction", "sea_surface_temperature"
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
# MICRO-SPOT DATABASE
# More specific than area names.
# =====================================================

fishing_spots = {
    "Leisure Bay Main Beach Gully": {
        "area": "Leisure Bay",
        "stand": (-30.823900, 30.406200),
        "cast": (-30.824250, 30.406650),
        "structure": "Dark sand gully with white-water edge",
        "feature_type": "gully",
        "depth_note": "Estimated deeper gully between shallow sandbanks",
        "confidence": 78,
        "species": ["Kob", "Shad", "Bronze Bream", "Blacktail", "Stone Bream", "Sand Shark", "Grey Shark", "Diamond Ray"],
        "notes": "Good beach structure. Fish the edge where white water meets darker channel.",
    },
    "Trafalgar Rock-Sand Transition": {
        "area": "Trafalgar",
        "stand": (-30.833900, 30.410500),
        "cast": (-30.834300, 30.411050),
        "structure": "Rock and sand transition with feeding gully",
        "feature_type": "gully",
        "depth_note": "Medium-depth gully near rock/sand transition",
        "confidence": 82,
        "species": ["Kob", "Shad", "Bronze Bream", "Blacktail", "Stone Bream", "Grey Shark", "Honeycomb Ray", "Diamond Ray"],
        "notes": "Strong structure option. Target the gully edge, not the middle.",
    },
    "Palm Beach White-Water Channel": {
        "area": "Palm Beach",
        "stand": (-30.867000, 30.382300),
        "cast": (-30.867420, 30.382850),
        "structure": "Working white water with channel edge",
        "feature_type": "white water",
        "depth_note": "Working white water over sandbank edge",
        "confidence": 74,
        "species": ["Shad", "Kob", "Garrick", "Bronze Bream", "Blacktail", "Pompano", "Grey Shark"],
        "notes": "Good if water is working. Better for Shad when there is visible white water.",
    },
    "Southbroom River-Mouth Channel": {
        "area": "Southbroom",
        "stand": (-30.919200, 30.328700),
        "cast": (-30.919650, 30.329300),
        "structure": "River-mouth influence with deeper channel",
        "feature_type": "river mouth",
        "depth_note": "Channel edge influenced by river-mouth water movement",
        "confidence": 76,
        "species": ["Kob", "Garrick", "Grunter", "Pompano", "Shad", "Sand Shark", "Grey Shark"],
        "notes": "Better around moving tide. Fish the channel and current seam.",
    },

    # Umhlanga micro-spots
    "Umhlanga Lighthouse Gully": {
        "area": "Umhlanga Lighthouse",
        "stand": (-29.717820, 31.089420),
        "cast": (-29.718050, 31.089880),
        "structure": "Deep gully near lighthouse rocks",
        "feature_type": "gully",
        "depth_note": "Rocky gully / deeper channel close to ledge",
        "confidence": 80,
        "species": ["Kob", "Garrick", "Shad", "Blacktail", "Bronze Bream", "Kingfish", "Rockcod"],
        "notes": "Fish the gully edge, not the flat water. Use caution on rocks.",
    },
    "Umhlanga Lagoon Mouth Current Seam": {
        "area": "Umhlanga Lagoon Mouth",
        "stand": (-29.720500, 31.088000),
        "cast": (-29.720900, 31.088600),
        "structure": "River mouth current seam and sandbank edge",
        "feature_type": "river mouth",
        "depth_note": "Moving water where lagoon flow meets surf line",
        "confidence": 82,
        "species": ["Garrick", "Kob", "Grunter", "Shad", "Pompano"],
        "notes": "Best around pushing or outgoing tide. Look for baitfish and current movement.",
    },
    "Bronze Beach Gully Section": {
        "area": "Bronze Beach",
        "stand": (-29.713900, 31.092000),
        "cast": (-29.714300, 31.092500),
        "structure": "Sandbank drop-off with working white water",
        "feature_type": "white water",
        "depth_note": "White-water edge over channel / sandbank drop",
        "confidence": 76,
        "species": ["Shad", "Kob", "Garrick", "Pompano", "Grey Shark"],
        "notes": "Good for Shad when white water is active. Cast into the working edge, not dead water.",
    },
}
# =====================================================
# SAFETY RATINGS
# =====================================================

safety_ratings = {
    "Leisure Bay Main Beach Gully": {
        "risk": "Medium",
        "advice": "Avoid isolated fishing at night. Prefer daylight or fish with others. Keep valuables out of sight.",
    },
    "Trafalgar Rock-Sand Transition": {
        "risk": "Medium",
        "advice": "Use known access points. Avoid leaving valuables visible in your vehicle. Be cautious early morning and night.",
    },
    "Palm Beach White-Water Channel": {
        "risk": "Medium",
        "advice": "Be cautious around quiet beach access points, especially early morning or night.",
    },
    "Southbroom River-Mouth Channel": {
        "risk": "Low to Medium",
        "advice": "Generally safer around active areas, but avoid isolated night fishing alone. Park in visible areas.",
    },
    "Umhlanga Lighthouse Gully": {
        "risk": "Medium",
        "advice": "Busy area but rock fishing can be risky. Avoid isolated rocks at night and watch for vehicle break-ins.",
    },
    "Umhlanga Lagoon Mouth Current Seam": {
        "risk": "Medium",
        "advice": "Be cautious around quiet access points. Avoid night fishing alone. Check lagoon/MPA restrictions.",
    },
    "Bronze Beach Gully Section": {
        "risk": "Medium",
        "advice": "Popular beach area, but still protect valuables and avoid isolated sections at night.",
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
    "Bronze Bream": {
        "ideal_baits": ["Prawn", "Red bait", "Mussel", "Crayfish"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Bronze Bream hold close to rocks, reef edges and foamy water.",
        "bait": "Prawn, red bait, mussel, crayfish where legal.",
        "trace": "Short scratching trace",
        "leader": "0.40mm to 0.55mm leader",
        "hooks": "1/0 to 3/0 strong hooks",
        "sinker": "2oz to 4oz sinker",
        "technique": "Fish closer in around rocks and foamy pockets. Do not overcast.",
        "bite_style": "Small taps → firm pull",
        "feel": "Small pecks, short sharp pulls, then strong movement into rocks.",
        "response": "Lift firmly once committed and keep pressure.",
        "mistake": "Fishing too far out.",
        "trace_image": "images/bronze_bream_trace.png",
        "bait_image": "images/prawn_bait.png",
        "trace_diagram": "Main Line\n|\nSwivel\n|\nShort leader\n|\nSmall strong hook\n|\nPrawn / red bait / mussel",
    },
    "Blacktail": {
        "ideal_baits": ["Prawn", "Sardine", "Mussel", "Red bait"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Blacktail feed close to rocks, gullies and foam pockets.",
        "bait": "Prawn, sardine pieces, mussel, red bait.",
        "trace": "Light scratching trace",
        "leader": "0.35mm to 0.45mm leader",
        "hooks": "Size 1 to 1/0 hooks",
        "sinker": "1oz to 3oz sinker",
        "technique": "Fish close-in around rocks and small gullies.",
        "bite_style": "Quick pecks → committed pull",
        "feel": "Rapid taps and short pulls.",
        "response": "Wait for a committed pull, then lift.",
        "mistake": "Using bait that is too large.",
        "trace_image": "images/blacktail_trace.png",
        "bait_image": "images/prawn_bait.png",
        "trace_diagram": "Main Line\n|\nSmall sinker\n|\nSwivel\n|\nLight leader\n|\nSmall hook",
    },
    "Grunter": {
        "ideal_baits": ["Prawn", "Cracker shrimp", "Worm"],
        "time_bonus": ["Evening", "Night"],
        "thinking": "Grunter feed over sandbanks, estuary edges and shallow channels.",
        "bait": "Prawn, cracker shrimp, worm.",
        "trace": "Light running trace",
        "leader": "0.35mm to 0.45mm leader",
        "hooks": "1/0 to 2/0 hooks",
        "sinker": "Light sinker only",
        "technique": "Present bait naturally. Avoid heavy tackle.",
        "bite_style": "Gentle pull → slow movement",
        "feel": "Line tightens slowly, fish may drop bait if resistance is high.",
        "response": "Let fish move with bait, then lift smoothly.",
        "mistake": "Using tackle that is too heavy.",
        "trace_image": "images/grunter_trace.png",
        "bait_image": "images/prawn_bait.png",
        "trace_diagram": "Main Line\n|\nSmall running sinker\n|\nSwivel\n|\nLight leader\n|\n1/0 - 2/0 hook",
    },
    "Pompano": {
        "ideal_baits": ["Prawn", "Worm", "Small crab"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Pompano feed in sandy channels and clean water near banks.",
        "bait": "Prawn, worm, small crab.",
        "trace": "Light running trace",
        "leader": "0.35mm to 0.50mm leader",
        "hooks": "1/0 to 3/0 hooks",
        "sinker": "2oz to 4oz sinker",
        "technique": "Cast to sandbank edges and allow bait to move naturally.",
        "bite_style": "Fast pickup → strong run",
        "feel": "Sharp pull then speed.",
        "response": "Lift smoothly and maintain pressure.",
        "mistake": "Too much heavy tackle.",
        "trace_image": "images/pompano_trace.png",
        "bait_image": "images/prawn_bait.png",
        "trace_diagram": "Main Line\n|\nRunning sinker\n|\nSwivel\n|\nLight leader\n|\nPrawn / worm bait",
    },
    "Sand Shark": {
        "ideal_baits": ["Sardine", "Mackerel", "Chokka", "Fish head"],
        "time_bonus": ["Evening", "Night", "Midnight"],
        "thinking": "Sand sharks feed in sandy channels and gullies.",
        "bait": "Sardine, mackerel, chokka, fish head.",
        "trace": "Strong non-edible trace",
        "leader": "Heavy nylon / steel depending on size",
        "hooks": "6/0 to 10/0 hooks",
        "sinker": "5oz to 8oz grapnel",
        "technique": "Cast into deeper channel and wait for steady run.",
        "bite_style": "Slow pickup → steady pull",
        "feel": "Rod loads and line pulls steadily.",
        "response": "Let pressure build, then set hook firmly.",
        "mistake": "Fishing too light.",
        "trace_image": "images/sand_shark_trace.png",
        "bait_image": "images/sardine_bait.png",
        "trace_diagram": "Main Line\n|\nHeavy leader\n|\nSinker clip\n|\nLarge hook bait",
    },
    "Grey Shark": {
        "ideal_baits": ["Sardine", "Mackerel", "Bonito", "Chokka"],
        "time_bonus": ["Evening", "Night", "Midnight"],
        "thinking": "Grey sharks patrol gullies, banks and channels.",
        "bait": "Sardine, mackerel, bonito, chokka.",
        "trace": "Steel or heavy shark trace",
        "leader": "Heavy leader with steel bite section",
        "hooks": "6/0 to 10/0 hooks",
        "sinker": "6oz to 8oz grapnel",
        "technique": "Fish deeper channels with solid bait presentation.",
        "bite_style": "Pickup → fast sustained run",
        "feel": "Line peels off steadily.",
        "response": "Let it run briefly, then apply pressure.",
        "mistake": "Weak bite trace.",
        "trace_image": "images/grey_shark_trace.png",
        "bait_image": "images/sardine_bait.png",
        "trace_diagram": "Main Line\n|\nHeavy leader\n|\nSteel bite trace\n|\nLarge hook",
    },
    "Diamond Ray": {
        "ideal_baits": ["Chokka", "Sardine", "Mackerel", "Octopus"],
        "time_bonus": ["Evening", "Night", "Midnight"],
        "thinking": "Diamond rays feed over sand and channel edges.",
        "bait": "Chokka, sardine, mackerel, octopus.",
        "trace": "Heavy sliding trace",
        "leader": "Heavy nylon leader",
        "hooks": "8/0 to 10/0 hooks",
        "sinker": "6oz to 8oz grapnel",
        "technique": "Fish sandy deeper channels. Expect heavy slow fight.",
        "bite_style": "Weighty pickup → heavy pull",
        "feel": "Dead weight followed by strong movement.",
        "response": "Apply steady pressure. Do not rush.",
        "mistake": "Trying to bully the fish too quickly.",
        "trace_image": "images/diamond_ray_trace.png",
        "bait_image": "images/sardine_bait.png",
        "trace_diagram": "Main Line\n|\nHeavy sinker clip\n|\nSwivel\n|\nHeavy leader\n|\nLarge hook bait",
    },
    "Honeycomb Ray": {
        "ideal_baits": ["Octopus", "Chokka", "Mackerel", "Sardine"],
        "time_bonus": ["Evening", "Night", "Midnight"],
        "thinking": "Honeycomb rays favour sandy gullies and deeper banks.",
        "bait": "Octopus, chokka, mackerel, sardine.",
        "trace": "Heavy ray trace",
        "leader": "Heavy nylon leader",
        "hooks": "8/0 to 12/0 hooks",
        "sinker": "6oz to 8oz grapnel",
        "technique": "Place bait in deeper channel and prepare for long fight.",
        "bite_style": "Slow pickup → very heavy pull",
        "feel": "Strong weight and slow powerful movement.",
        "response": "Keep steady pressure and manage drag.",
        "mistake": "Underestimating fight time.",
        "trace_image": "images/honeycomb_ray_trace.png",
        "bait_image": "images/octopus_bait.png",
        "trace_diagram": "Main Line\n|\nHeavy leader\n|\nLarge hook\n|\nLarge bait",
    },
}

# Ensure all fish in spot database have species info
for fish_name in sorted({fish for s in fishing_spots.values() for fish in s["species"]}):
    if fish_name not in species_engine:
        base = species_engine["Kob"]
        species_engine[fish_name] = base.copy()
        species_engine[fish_name]["thinking"] = f"{fish_name} uses prototype rules. Refine with local species data."
        species_engine[fish_name]["trace_image"] = f"images/{fish_name.lower().replace(' ', '_')}_trace.png"

# =====================================================
# REGULATION ENGINE - MOCKUP / PROTOTYPE
# =====================================================

regulation_data = {
    "Blacktail": {"bag": "5", "min_size": "20 cm", "closed": "Open", "protected": "No", "mpa": "Check selected area", "feedback": "Warn if >5 or undersize"},
    "Bronze Bream": {"bag": "2", "min_size": "30 cm", "closed": "Open", "protected": "No", "mpa": "Check selected area", "feedback": "Warn if >2 or undersize"},
    "Garrick": {"bag": "2", "min_size": "70 cm", "closed": "Verify current season", "protected": "No", "mpa": "Check selected area", "feedback": "Warn limits"},
    "Grunter": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "No", "mpa": "Check selected area", "feedback": "Ask user to confirm"},
    "Kob": {"bag": "Varies", "min_size": "Varies by area/method", "closed": "Verify local rules", "protected": "No", "mpa": "Check selected area", "feedback": "Ask shore/estuary/boat"},
    "Pompano": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "No", "mpa": "Check selected area", "feedback": "Log size/quantity"},
    "Shad": {"bag": "4", "min_size": "30 cm", "closed": "Seasonal closure applies", "protected": "No", "mpa": "Check selected area", "feedback": "Block keep in closure"},
}

regulation_table = pd.DataFrame([
    {
        "Fish": fish,
        "Bag Limit": data["bag"],
        "Minimum Size": data["min_size"],
        "Closed Season": data["closed"],
        "Protected": data["protected"],
        "MPA Check": data["mpa"],
        "Feedback Rule": data["feedback"],
    }
    for fish, data in sorted(regulation_data.items())
])

# =====================================================
# MAIN INPUTS - SIDEBAR
# =====================================================

st.sidebar.header("📍 Location")

location_method = st.sidebar.radio(
    "Choose location method",
    ["Use current GPS", "Enter coordinates", "Choose planning area"]
)

location_basis = "Unknown"

if location_method == "Use current GPS":
    location = streamlit_geolocation()

    if location and location.get("latitude") is not None:
        user_location = (location["latitude"], location["longitude"])
        location_basis = "Current GPS location"
        st.sidebar.success(f"GPS found: {user_location[0]:.6f}, {user_location[1]:.6f}")
    else:
        user_location = (-30.823900, 30.406200)
        location_basis = "Fallback: Leisure Bay sample"
        st.sidebar.warning("GPS not available. Using Leisure Bay sample.")

elif location_method == "Enter coordinates":
    manual_lat = st.sidebar.number_input("Latitude", value=-30.823900, format="%.6f")
    manual_lon = st.sidebar.number_input("Longitude", value=30.406200, format="%.6f")
    user_location = (manual_lat, manual_lon)
    location_basis = f"Entered coordinates: {manual_lat:.6f}, {manual_lon:.6f}"
    st.sidebar.success(location_basis)

else:
    selected_area = st.sidebar.selectbox(
        "Where will you be fishing from?",
        list(area_locations.keys())
    )
    user_location = area_locations[selected_area]
    location_basis = f"Planning from: {selected_area}"
    st.sidebar.success(location_basis)

st.sidebar.header("🎯 Trip Setup")

trip_date = st.sidebar.date_input("Fishing date", value=datetime.today())

time_bucket = st.sidebar.selectbox("Preferred fishing time", list(time_bucket_windows.keys()))

tide_stage = st.sidebar.selectbox(
    "Tide stage",
    ["Pushing tide", "Outgoing tide", "High tide turning", "Low tide turning", "Slack / not sure"]
)

max_travel_km = st.sidebar.selectbox(
    "How far are you willing to travel?",
    [2, 5, 10, 20, 50, 100],
    index=2
)

casting_ability = st.sidebar.selectbox(
    "Casting ability",
    ["Beginner: 20–40m", "Average: 40–70m", "Strong caster: 70–110m", "Advanced: 110m+"],
    index=1
)

preferred_target = st.sidebar.selectbox(
    "Preferred target species",
    ["Auto select"] + list(species_engine.keys())
)

available_baits = st.sidebar.multiselect(
    "Bait you have available - select up to 10",
    all_baits,
    max_selections=10
)

# =====================================================
# RECOMMENDATION ENGINE
# =====================================================

closest_name = None
closest_distance = float("inf")

for name, spot_data in fishing_spots.items():
    dist_km = geodesic(user_location, spot_data["stand"]).km

    if dist_km < closest_distance:
        closest_distance = dist_km
        closest_name = name

candidates = []

for name, spot_data in fishing_spots.items():
    dist_km = geodesic(user_location, spot_data["stand"]).km

    if dist_km <= max_travel_km:
        score = spot_data["confidence"]

        # Structure score
        if spot_data["feature_type"] in ["gully", "river mouth", "white water"]:
            score += 8

        # Time advantage
        for fish in spot_data["species"]:
            if fish in species_engine and time_bucket in species_engine[fish]["time_bonus"]:
                score += 4

        # Bait advantage
        for fish in spot_data["species"]:
            if fish in species_engine:
                bait_status_temp, _, _ = bait_match_engine(
                    available_baits,
                    species_engine[fish]["ideal_baits"]
                )
                if bait_status_temp == "Good match":
                    score += 4

        # Distance practicality
        if dist_km <= 5:
            score += 5
        elif dist_km <= 10:
            score += 3
        elif dist_km <= 20:
            score += 1

        candidates.append((name, dist_km, score))

if not candidates:
    st.warning("No fishing spots found within your selected radius. Showing closest available spot instead.")
    candidates.append((closest_name, closest_distance, fishing_spots[closest_name]["confidence"]))

candidates.sort(key=lambda x: x[2], reverse=True)

best_spot_name = candidates[0][0]
best_distance = candidates[0][1]
best_review_score = candidates[0][2]

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
        if fish not in species_engine:
            continue

        score = 50

        if time_bucket in species_engine[fish]["time_bonus"]:
            score += 12

        bait_status_temp, _, _ = bait_match_engine(
            available_baits,
            species_engine[fish]["ideal_baits"]
        )

        if bait_status_temp == "Good match":
            score += 10
        elif bait_status_temp == "Poor match":
            score -= 8

        ranked.append((fish, score))

    ranked.sort(key=lambda x: x[1], reverse=True)
    selected_species = ranked[0][0]
else:
    selected_species = preferred_target

species = species_engine[selected_species]

bait_status, matched_baits, bait_message = bait_match_engine(
    available_baits,
    species["ideal_baits"]
)

alternative_targets = []

for fish in likely_species:
    if fish in species_engine:
        alt_status, _, _ = bait_match_engine(
            available_baits,
            species_engine[fish]["ideal_baits"]
        )
        if alt_status == "Good match" and fish != selected_species:
            alternative_targets.append(fish)

conditions = fetch_conditions(stand[0], stand[1], trip_date, time_bucket)
moon_phase = moon_phase_name(trip_date)

condition_score, cond_pos, cond_neg = condition_score_engine(
    conditions,
    tide_stage,
    moon_phase,
    selected_species,
    time_bucket
)

confidence = spot["confidence"]

if selected_species in likely_species:
    confidence += 5
else:
    confidence -= 8

if time_bucket in species["time_bonus"]:
    confidence += 8
    time_reason = f"{selected_species} is favoured during {time_bucket}."
else:
    confidence -= 3
    time_reason = f"{time_bucket} is not the strongest time for {selected_species}."

if bait_status == "Good match":
    confidence += 5
elif bait_status == "Poor match":
    confidence -= 10

confidence = int((confidence * 0.65) + (condition_score * 0.35))
confidence = max(0, min(95, confidence))

# Bait image logic: prefer bait user has, then fallback to species ideal image
matched_bait_image = None
matched_bait_name = None

for bait in available_baits:
    if bait in species["ideal_baits"]:
        matched_bait_image = bait_image_lookup.get(bait)
        matched_bait_name = bait
        break

if matched_bait_image:
    bait_image_path = matched_bait_image
    bait_image_caption = f"Use your available bait: {matched_bait_name}"
else:
    bait_image_name = species.get("bait_image", "").split("/")[-1]
    bait_image_path = f"images/{bait_image_name}"
    bait_image_caption = f"Ideal bait presentation for {selected_species}"

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
# HOME
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
    ✅ Uses specific micro-spots, not just broad area names  
    ✅ Shows stand point and cast target  
    ✅ Suggests bait and trace setup  
    ✅ Shows finished bait presentation  
    ✅ Reviews wind, weather, swell, tide and moon  
    ✅ Adds safety and responsible fishing prompts  
    ✅ Learns from your feedback over time  
    """)

    st.info("Start in the 🎯 Recommendation tab. Your settings are controlled from the sidebar.")
    st.warning("CastIQ does not guarantee fish. It reduces guesswork and improves decision-making.")

# =====================================================
# RECOMMENDATION
# =====================================================

with tabs[1]:
    st.header("🎯 Best Fishing Recommendation")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.metric("My best recommendation", best_spot_name)
        st.write(f"**Location basis:** {location_basis}")
        st.write(f"**Distance from selected planning point:** {best_distance:.2f} km")
        st.write(f"**Travel radius selected:** {max_travel_km} km")
        st.write(f"**Closest available spot:** {closest_name} ({closest_distance:.2f} km)")
        st.write(f"**Area:** {spot['area']}")
        st.write(f"**Structure:** {spot['structure']}")
        st.write(f"**Depth note:** {spot['depth_note']}")
        st.write(f"**Why this spot:** {spot['notes']}")
        st.write(f"**Micro-spot review score:** {best_review_score}")

    with col2:
        st.metric("Fishing confidence", f"{confidence}%")
        st.write(f"**Confidence level:** {confidence_label(confidence)}")
        st.write(f"**Selected target:** {selected_species}")
        st.write(f"**Time:** {time_bucket} ({time_bucket_windows[time_bucket]})")
        st.write(f"**Time logic:** {time_reason}")
        st.write(f"**Bait logic:** {bait_message}")
        st.write(f"**Conditions score:** {condition_score}%")

    st.subheader("📍 Stand Here → Cast There")

    a, b, c, d = st.columns(4)
    a.metric("Stand GPS", f"{stand[0]:.6f}, {stand[1]:.6f}")
    b.metric("Cast GPS", f"{cast[0]:.6f}, {cast[1]:.6f}")
    c.metric("Cast Distance", f"{int(cast_distance)} m")
    d.metric("Direction", f"{int(bearing)}° {compass}")

    st.info(
        f"Stand at the GPS point. Face {int(bearing)}° {compass}. "
        f"Cast approximately {int(cast_distance)}m into the target structure."
    )

    if "Beginner" in casting_ability and cast_distance > 40:
        st.warning("This target may be too far for a beginner. Look for closer white water or a near-shore channel.")
    elif "Average" in casting_ability and cast_distance > 70:
        st.warning("This cast is at the upper end for an average caster.")
    elif "Strong" in casting_ability and cast_distance > 110:
        st.warning("This cast may be beyond strong-caster range.")
    else:
        st.success("This casting distance matches your selected ability range.")

# =====================================================
# MAP
# =====================================================

with tabs[2]:
    st.header("🛰️ Map + Navigation")

    map_center = [(stand[0] + cast[0]) / 2, (stand[1] + cast[1]) / 2]
    m = folium.Map(location=map_center, zoom_start=17, tiles=None)

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
        overlay=False,
        control=True
    ).add_to(m)

    folium.Marker(
        [user_location[0], user_location[1]],
        popup="Selected/current location",
        tooltip="Planning point",
        icon=folium.Icon(color="blue", icon="user")
    ).add_to(m)

    folium.Marker(
        [stand[0], stand[1]],
        popup="Stand here",
        tooltip="Stand here",
        icon=folium.Icon(color="green", icon="flag")
    ).add_to(m)

    folium.Marker(
        [cast[0], cast[1]],
        popup=f"Cast target: {int(cast_distance)}m",
        tooltip="Cast target",
        icon=folium.Icon(color="red", icon="screenshot")
    ).add_to(m)

    folium.PolyLine(
        [[stand[0], stand[1]], [cast[0], cast[1]]],
        weight=5,
        opacity=0.9,
        tooltip=f"Cast {int(cast_distance)}m at {int(bearing)}° {compass}"
    ).add_to(m)

    folium.Circle(
        [cast[0], cast[1]],
        radius=15,
        popup="Estimated bait landing zone / target gully",
        tooltip="Bait landing zone",
        fill=True
    ).add_to(m)

    st_folium(m, width=1150, height=560)

    st.subheader("🧭 Take Me There")

    google_drive = f"https://www.google.com/maps/dir/?api=1&destination={stand[0]},{stand[1]}&travelmode=driving"
    google_walk = f"https://www.google.com/maps/dir/?api=1&destination={stand[0]},{stand[1]}&travelmode=walking"
    waze = f"https://waze.com/ul?ll={stand[0]},{stand[1]}&navigate=yes"

    nav_choice = st.selectbox(
        "Choose navigation option",
        ["Google Maps - Drive", "Google Maps - Walk", "Waze"]
    )

    if nav_choice == "Google Maps - Drive":
        st.link_button("🚗 Open Google Maps Driving", google_drive)
    elif nav_choice == "Google Maps - Walk":
        st.link_button("🚶 Open Google Maps Walking", google_walk)
    else:
        st.link_button("🚘 Open Waze", waze)

    st.caption("Navigation opens outside CastIQ. Confirm access route, parking and local restrictions before travelling.")

# =====================================================
# BAIT + TRACE
# =====================================================

with tabs[3]:
    st.header("🎣 Bait & Trace")

    st.subheader("Bait Decision")
    st.write(f"**Selected target:** {selected_species}")
    st.write(f"**Ideal bait:** {', '.join(species['ideal_baits'])}")

    if available_baits:
        st.write(f"**Bait you have:** {', '.join(available_baits)}")

    if bait_status == "Good match":
        st.success(f"✅ {bait_message}")
    elif bait_status == "Poor match":
        st.warning(f"⚠️ {bait_message}")

        if alternative_targets:
            st.info(f"Better target based on your bait at this spot: {', '.join(alternative_targets)}")
        else:
            st.info(f"Recommended to obtain: {', '.join(species['ideal_baits'])}")
    else:
        st.info("Select bait in the sidebar to get bait-matching advice.")

    st.subheader("🖼️ Finished Bait Presentation")

    if bait_image_path and os.path.exists(bait_image_path):
        st.image(bait_image_path, caption=bait_image_caption, use_container_width=True)
    else:
        st.info(f"Bait image not loaded yet. Add image here: {bait_image_path}")

    st.subheader("🧵 Trace Recommendation")

    trace_image_path = species.get("trace_image")

    if trace_image_path and os.path.exists(trace_image_path):
        st.image(trace_image_path, caption=f"{selected_species} completed trace setup", use_container_width=True)
    else:
        st.info(f"Trace image not loaded yet. Add image here: {trace_image_path}")
        st.code(species["trace_diagram"])

    st.subheader("🐟 Bite Behaviour")
    st.write(f"**Bite style:** {species['bite_style']}")
    st.write(f"**What it feels like:** {species['feel']}")
    st.write(f"**What you must do:** {species['response']}")
    st.warning(f"Common mistake: {species['mistake']}")

# =====================================================
# CONDITIONS
# =====================================================

with tabs[4]:
    st.header("🌊 Fishing Conditions Summary")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Weather")
        if conditions.get("available"):
            st.write(f"Temperature: {conditions.get('temperature')} °C")
            st.write(f"Weather: {weather_code_text(conditions.get('weather_code'))}")
            st.write(f"Rain probability: {conditions.get('rain_probability')}%")
            st.write(f"Pressure: {conditions.get('pressure')} hPa")
            st.write(f"Cloud cover: {conditions.get('cloud_cover')}%")
        else:
            st.warning("Weather data unavailable.")

    with col2:
        st.subheader("Wind + Marine")
        st.write(f"Wind: {conditions.get('wind_speed')} km/h from {direction_text(conditions.get('wind_direction'))}")
        st.write(f"Wave height: {conditions.get('wave_height')} m")
        st.write(f"Wave period: {conditions.get('wave_period')} sec")
        st.write(f"Wave direction: {direction_text(conditions.get('wave_direction'))}")
        st.write(f"Sea temperature: {conditions.get('sea_temp')} °C")

    with col3:
        st.subheader("Tide + Moon")
        st.write(f"Tide stage: {tide_stage}")
        st.write(f"Moon phase: {moon_phase}")
        st.metric("Conditions score", f"{condition_score}%")

    if cond_pos:
        st.success("Positive signals: " + " | ".join(cond_pos))
    if cond_neg:
        st.warning("Caution signals: " + " | ".join(cond_neg))

# =====================================================
# SAFETY
# =====================================================

with tabs[5]:
    st.header("🛡️ Safety")

    safety = safety_ratings.get(best_spot_name, {
        "risk": "Unknown",
        "advice": "No safety profile loaded yet. Fish with caution and verify local conditions."
    })

    risk = safety["risk"]

    if "Low" in risk and "Medium" not in risk:
        st.success(f"Safety risk: {risk}")
    elif "Medium" in risk:
        st.warning(f"Safety risk: {risk}")
    else:
        st.error(f"Safety risk: {risk}")

    st.write(f"**Safety advice:** {safety['advice']}")

    st.warning("""
    Safety prompts:
    - Avoid isolated fishing at night.
    - Do not leave valuables visible in your vehicle.
    - Check wave sets before fishing rocks.
    - Fish with someone where practical.
    - Avoid closed, restricted or unsafe access areas.
    """)

# =====================================================
# REGULATIONS
# =====================================================

with tabs[6]:
    st.header("📏 Regulation Engine")

    st.subheader(f"Selected Target Regulation: {selected_species}")

    reg = regulation_data.get(selected_species)

    if reg:
        r1, r2, r3 = st.columns(3)
        r1.metric("Bag limit", reg["bag"])
        r2.metric("Minimum size", reg["min_size"])
        r3.metric("Protected", reg["protected"])

        st.write(f"**Closed season:** {reg['closed']}")
        st.write(f"**MPA check:** {reg['mpa']}")
        st.write(f"**Feedback rule:** {reg['feedback']}")
    else:
        st.warning("Regulation record not loaded yet for this species.")

    st.subheader("Full Regulation Table")
    st.dataframe(regulation_table, use_container_width=True)

    st.warning(
        "Prototype regulation guide only. Always verify current South African recreational fishing rules, local bylaws and MPA restrictions before keeping fish."
    )

# =====================================================
# PACKAGES
# =====================================================

with tabs[7]:
    st.header("💎 Packages")

    p1, p2, p3, p4 = st.columns(4)

    with p1:
        st.subheader("Free")
        st.write("Basic area guidance, responsible fishing reminders.")
        st.video("https://www.youtube.com/watch?v=REPLACE_FREE_VIDEO_ID")

    with p2:
        st.subheader("Pro")
        st.write("Exact GPS stand/cast, bait matching, trace visuals.")
        st.video("https://www.youtube.com/watch?v=REPLACE_PRO_VIDEO_ID")

    with p3:
        st.subheader("Elite")
        st.write("Conditions intelligence, micro-spot ranking, premium logic.")
        st.video("https://www.youtube.com/watch?v=REPLACE_ELITE_VIDEO_ID")

    with p4:
        st.subheader("Guide")
        st.write("Client planning, group sessions, trip reports.")
        st.video("https://www.youtube.com/watch?v=REPLACE_GUIDE_VIDEO_ID")

# =====================================================
# GUIDE
# =====================================================

with tabs[8]:
    st.header("📘 User Guide")

    st.markdown("""
    ### How to use CastIQ Pro

    1. Choose your location method in the sidebar.
    2. Select where you are or where you plan to fish from.
    3. Choose how far you are willing to travel.
    4. Select time, tide stage, bait and target species.
    5. Review the best micro-spot recommendation.
    6. Open the Map tab for stand/cast points.
    7. Check bait, trace, conditions, safety and regulations.
    8. Fish responsibly.
    9. Submit feedback after the session.
    """)

# =====================================================
# FAQ
# =====================================================

with tabs[9]:
    st.header("❓ FAQ")

    st.markdown("""
    **Does CastIQ guarantee fish?**  
    No. It improves decision-making but fishing still depends on real conditions.

    **Why does the app choose one spot over another?**  
    It scores structure, distance, time, bait suitability, species match and conditions.

    **Why is the spot now more specific than just Umhlanga?**  
    The app now uses micro-spots such as Lighthouse Gully, Lagoon Mouth and Bronze Beach Gully.

    **Why does bait matter?**  
    Different fish feed differently. The app checks what you have against the target species.

    **Why do I need to check safety and regulations?**  
    Because better fishing intelligence must be matched with responsible behaviour.

    **Does this work outside South Africa?**  
    The model can be expanded globally by loading local spots, species and regulations.
    """)

# =====================================================
# FEEDBACK
# =====================================================

st.divider()
st.subheader("💬 Feedback / Accuracy Improvement")

with st.form("feedback_form"):
    result = st.selectbox(
        "Did the recommendation work?",
        ["Not fished yet", "Yes - caught fish", "Had bites only", "No action", "Wrong spot", "Wrong bait", "Wrong trace", "Wrong species"]
    )

    actual_species = st.text_input("What species did you catch or see?")
    actual_bait = st.text_input("What bait worked or failed?")
    catch_outcome = st.selectbox("Catch outcome", ["No catch", "Released", "Kept legally", "Unsure"])
    comments = st.text_area("Your suggestion / improvement")

    submitted = st.form_submit_button("Submit Feedback")

    if submitted:
        feedback = {
            "timestamp": datetime.now().isoformat(),
            "location_basis": location_basis,
            "user_lat": user_location[0],
            "user_lon": user_location[1],
            "trip_date": str(trip_date),
            "time_bucket": time_bucket,
            "tide_stage": tide_stage,
            "condition_score": condition_score,
            "travel_range_km": max_travel_km,
            "closest_spot": closest_name,
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
