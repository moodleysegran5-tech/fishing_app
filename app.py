import math
import os
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional, Any

import pandas as pd
import requests
import streamlit as st

try:
    import folium
    from streamlit_folium import st_folium
except Exception:
    folium = None
    st_folium = None

try:
    from geopy.distance import geodesic
except Exception:
    geodesic = None

try:
    from streamlit_geolocation import streamlit_geolocation
except Exception:
    streamlit_geolocation = None


# =====================================================
# CastIQ Pro — corrected full app.py
# Key upgrades:
# - Safe secrets handling: no StreamlitSecretNotFoundError
# - SA-wide location search using OpenStreetMap Nominatim
# - Coastline snapping engine with Overpass fallback profiles
# - Unified confidence engine: table and loaded card use same score
# - Ranked recommendations with selectable option
# - Bait mismatch correction
# - Parking -> stand navigation
# - Human-friendly cast direction
# - Beach mode
# =====================================================

st.set_page_config(page_title="CastIQ Pro", page_icon="🎣", layout="wide")

APP_NAME = "CastIQ Pro"
FEEDBACK_FILE = "feedback_log.csv"
API_CACHE_TTL_SECONDS = 1800
REQUEST_HEADERS = {
    "User-Agent": "CastIQ-Pro/1.0 contact=local-test",
    "Accept": "application/json",
}


# =====================================================
# Safe config / secrets
# =====================================================

def get_secret_safe(key: str, default: str = "") -> str:
    """
    Streamlit raises StreamlitSecretNotFoundError if no secrets.toml exists.
    This function prevents that crash.
    """
    try:
        return str(st.secrets[key])
    except Exception:
        return default


WORLD_TIDES_API_KEY = get_secret_safe("WORLD_TIDES_API_KEY", "")
STORMGLASS_API_KEY = get_secret_safe("STORMGLASS_API_KEY", "")


# =====================================================
# Utilities
# =====================================================

def safe_request_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 12,
    retries: int = 1,
) -> Optional[Any]:
    hdrs = REQUEST_HEADERS.copy()
    if headers:
        hdrs.update(headers)

    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
    return None


def distance_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    if geodesic:
        return geodesic(a, b).km
    return haversine_km(a[0], a[1], b[0], b[1])


def distance_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return distance_km(a, b) * 1000


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def destination_point(origin: Tuple[float, float], bearing_deg: float, distance_meters: float) -> Tuple[float, float]:
    lat1 = math.radians(origin[0])
    lon1 = math.radians(origin[1])
    brng = math.radians(bearing_deg)
    r = 6371000.0
    d = distance_meters / r

    lat2 = math.asin(
        math.sin(lat1) * math.cos(d)
        + math.cos(lat1) * math.sin(d) * math.cos(brng)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lat2), math.degrees(lon2))


def calculate_bearing(start: Tuple[float, float], end: Tuple[float, float]) -> float:
    lat1 = math.radians(start[0])
    lat2 = math.radians(end[0])
    dlon = math.radians(end[1] - start[1])

    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def bearing_to_compass(bearing: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((bearing + 11.25) / 22.5) % 16]


def opposite_bearing(bearing: float) -> float:
    return (bearing + 180) % 360


def confidence_label(score: int) -> str:
    if score >= 80:
        return "High"
    if score >= 65:
        return "Medium"
    if score >= 50:
        return "Fair"
    return "Low"


def human_direction_text(compass: str) -> str:
    if compass in ["E", "ENE", "ESE"]:
        return "Stand facing the sea and turn slightly right."
    if compass in ["SE", "SSE"]:
        return "Stand facing the sea and angle your cast to the right."
    if compass in ["NE", "NNE"]:
        return "Stand facing the sea and angle your cast to the left."
    if compass in ["S", "N"]:
        return "Stand facing the sea and cast straight into the working water."
    if "W" in compass:
        return "Stand facing the sea and check the map arrow carefully before casting."
    return "Stand facing the sea and follow the map arrow."


def weather_code_text(code):
    if code is None:
        return "Unknown"
    mapping = {
        0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing rime fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain",
        80: "Rain showers", 81: "Rain showers", 82: "Violent rain showers",
        95: "Thunderstorm",
    }
    return mapping.get(int(code), f"Weather code {code}")


def direction_text(deg):
    if deg is None:
        return "unknown"
    return f"{int(deg)}° {bearing_to_compass(float(deg))}"


def moon_phase_name(d: date) -> str:
    # Simple approximation. Good enough for scoring fallback, not a legal/tide source.
    known_new_moon = date(2000, 1, 6)
    days = (d - known_new_moon).days
    phase = days % 29.53058867
    if phase < 1.84566:
        return "New Moon"
    if phase < 5.53699:
        return "Waxing Crescent"
    if phase < 9.22831:
        return "First Quarter"
    if phase < 12.91963:
        return "Waxing Gibbous"
    if phase < 16.61096:
        return "Full Moon"
    if phase < 20.30228:
        return "Waning Gibbous"
    if phase < 23.99361:
        return "Last Quarter"
    if phase < 27.68493:
        return "Waning Crescent"
    return "New Moon"


# =====================================================
# Time, baits, species, regulations
# =====================================================

TIME_BUCKET_WINDOWS = {
    "Early Morning": "04:30 – 07:30",
    "Morning": "07:30 – 10:30",
    "Midday": "10:30 – 14:30",
    "Afternoon": "14:30 – 17:00",
    "Evening": "17:00 – 20:00",
    "Night": "20:00 – 23:59",
    "Midnight": "00:00 – 04:30",
}
TIME_BUCKET_HOUR = {
    "Early Morning": 6, "Morning": 9, "Midday": 12, "Afternoon": 15,
    "Evening": 18, "Night": 21, "Midnight": 2
}

ALL_BAITS = [
    "Sardine", "Chokka", "Mackerel", "Red bait", "Prawn", "Mussel",
    "Cracker shrimp", "Worm", "Live mullet", "Fish head", "Octopus",
    "Bonito", "Spoon lure", "Paddle tail lure", "Small crab", "Crayfish",
    "Fish fillet", "White mussel", "Bloodworm", "Sealice", "Pilchard",
]

SPECIES: Dict[str, Dict[str, Any]] = {
    "Kob": {
        "ideal_baits": ["Chokka", "Sardine", "Mackerel", "Live mullet", "Fish fillet", "Pilchard"],
        "time_bonus": ["Early Morning", "Evening", "Night", "Midnight"],
        "trace": "Sliding sinker trace",
        "bite_style": "Soft pickup → suction feed → slow run",
        "feel": "Light taps then rod loads",
        "response": "Wait for the rod to load, then lift firmly.",
        "mistake": "Striking too early.",
        "trace_diagram": "Main line | running sinker | swivel | 60–80cm leader | 5/0–7/0 hook",
    },
    "Shad / Elf": {
        "ideal_baits": ["Sardine", "Pilchard", "Chokka", "Spoon lure"],
        "time_bonus": ["Early Morning", "Morning", "Afternoon", "Evening"],
        "trace": "Short steel trace",
        "bite_style": "Fast repeated hits",
        "feel": "Sharp taps and fast movement",
        "response": "Strike quickly and keep pressure.",
        "mistake": "Using no steel when bite-offs are likely.",
        "trace_diagram": "Main line | swivel | short steel | 1/0–3/0 hook",
    },
    "Garrick / Leervis": {
        "ideal_baits": ["Live mullet", "Paddle tail lure", "Spoon lure"],
        "time_bonus": ["Morning", "Afternoon", "Evening"],
        "trace": "Live bait trace or lure leader",
        "bite_style": "Aggressive grab → fast run",
        "feel": "Strong pull and line speed",
        "response": "Let the fish turn, then apply steady pressure.",
        "mistake": "Striking too hard before the fish commits.",
        "trace_diagram": "Main line | swivel | leader | 6/0–8/0 circle hook",
    },
    "Bronze Bream": {
        "ideal_baits": ["Prawn", "Red bait", "Mussel", "Crayfish", "White mussel"],
        "time_bonus": ["Morning", "Afternoon"],
        "trace": "Short scratching trace",
        "bite_style": "Small taps → firm pull",
        "feel": "Pecks then strong pull into rocks",
        "response": "Lift firmly when committed.",
        "mistake": "Fishing too far from the rocks.",
        "trace_diagram": "Main line | swivel | short leader | small strong hook",
    },
    "Blacktail": {
        "ideal_baits": ["Prawn", "Mussel", "Red bait", "Cracker shrimp", "Worm"],
        "time_bonus": ["Morning", "Afternoon", "Evening"],
        "trace": "Light scratching trace",
        "bite_style": "Quick pecks and small pulls",
        "feel": "Taps close to rocks",
        "response": "Keep bait small and present naturally.",
        "mistake": "Oversized bait.",
        "trace_diagram": "Main line | small sinker | swivel | short leader | 1/0 hook",
    },
    "Spotted Grunter": {
        "ideal_baits": ["Prawn", "Cracker shrimp", "Worm", "Bloodworm", "Sealice"],
        "time_bonus": ["Early Morning", "Evening", "Night"],
        "trace": "Light running sinker trace",
        "bite_style": "Gentle pickup then steady pull",
        "feel": "Soft taps then slow run",
        "response": "Allow pickup before lifting.",
        "mistake": "Heavy tackle and too much resistance.",
        "trace_diagram": "Main line | running sinker | swivel | 60cm leader | 1/0–2/0 hook",
    },
    "Pompano": {
        "ideal_baits": ["Prawn", "Cracker shrimp", "Small crab", "White mussel", "Worm"],
        "time_bonus": ["Morning", "Afternoon"],
        "trace": "Light surf scratching trace",
        "bite_style": "Sharp taps in shallow working water",
        "feel": "Fast, nervous taps",
        "response": "Keep bait near sandbank edges.",
        "mistake": "Casting beyond the productive zone.",
        "trace_diagram": "Main line | light sinker | short leader | small hook",
    },
    "White Steenbras": {
        "ideal_baits": ["Prawn", "Worm", "Bloodworm", "White mussel", "Cracker shrimp"],
        "time_bonus": ["Early Morning", "Evening", "Night"],
        "trace": "Long running sinker trace",
        "bite_style": "Slow pickup and strong pull",
        "feel": "Rod loads gradually",
        "response": "Do not rush the strike.",
        "mistake": "Too much tension on pickup.",
        "trace_diagram": "Main line | running sinker | swivel | 80cm leader | 2/0–4/0 hook",
    },
    "Sand Steenbras": {
        "ideal_baits": ["Prawn", "Worm", "Bloodworm", "White mussel"],
        "time_bonus": ["Morning", "Afternoon", "Evening"],
        "trace": "Light running sinker trace",
        "bite_style": "Soft bite in sandy gutters",
        "feel": "Small taps then weight",
        "response": "Use patience and light drag.",
        "mistake": "Too heavy terminal tackle.",
        "trace_diagram": "Main line | running sinker | swivel | leader | 1/0–3/0 hook",
    },
    "Galjoen": {
        "ideal_baits": ["Red bait", "White mussel", "Mussel", "Prawn"],
        "time_bonus": ["Morning", "Afternoon"],
        "trace": "Rocky-water scratching trace",
        "bite_style": "Strong knocks in white water",
        "feel": "Knock-knock then weight",
        "response": "Keep pressure away from rocks.",
        "mistake": "Fishing calm clear water.",
        "trace_diagram": "Main line | sinker | swivel | short leader | strong small hook",
    },
    "White Musselcracker": {
        "ideal_baits": ["Crab", "Small crab", "Crayfish", "Mussel", "Red bait"],
        "time_bonus": ["Morning", "Afternoon"],
        "trace": "Heavy scratching / cracker trace",
        "bite_style": "Heavy crush and hard pull",
        "feel": "Sudden weight and power",
        "response": "Strike hard and hold away from rocks.",
        "mistake": "Fishing tackle too light.",
        "trace_diagram": "Main line | strong leader | heavy hook | bait close to reef",
    },
    "Kingfish": {
        "ideal_baits": ["Live mullet", "Paddle tail lure", "Spoon lure", "Bonito"],
        "time_bonus": ["Early Morning", "Morning", "Evening"],
        "trace": "Lure leader or live bait trace",
        "bite_style": "Fast hit and aggressive run",
        "feel": "Explosive pull",
        "response": "Keep pressure and manage drag.",
        "mistake": "Weak leader near rocks.",
        "trace_diagram": "Main line | leader | lure/live bait hook",
    },
    "Grey Shark": {
        "ideal_baits": ["Mackerel", "Fish head", "Bonito", "Sardine", "Fish fillet"],
        "time_bonus": ["Evening", "Night"],
        "trace": "Steel bite trace",
        "bite_style": "Strong pickup and sustained run",
        "feel": "Heavy pull and line speed",
        "response": "Let it run, then set pressure.",
        "mistake": "No bite protection.",
        "trace_diagram": "Main line | heavy sinker | steel trace | 6/0–9/0 hook",
    },
    "Sand Shark": {
        "ideal_baits": ["Mackerel", "Sardine", "Fish fillet", "Chokka"],
        "time_bonus": ["Evening", "Night"],
        "trace": "Medium shark trace",
        "bite_style": "Steady pull and weight",
        "feel": "Rod loads heavily",
        "response": "Apply steady pressure.",
        "mistake": "Dragging too hard in shallow water.",
        "trace_diagram": "Main line | sinker | steel/mono leader | strong hook",
    },
    "Spotted Gully Shark": {
        "ideal_baits": ["Sardine", "Mackerel", "Chokka", "Fish fillet"],
        "time_bonus": ["Evening", "Night"],
        "trace": "Medium steel trace",
        "bite_style": "Pickup near gullies",
        "feel": "Taps then strong weight",
        "response": "Keep fish out of reef.",
        "mistake": "Fishing too light in rocky gullies.",
        "trace_diagram": "Main line | sinker | steel trace | strong hook",
    },
}

REGULATIONS = {
    "Blacktail": {"bag": "5", "min_size": "20 cm", "closed": "Open", "protected": "No", "note": "Check latest local rules."},
    "Bronze Bream": {"bag": "2", "min_size": "30 cm", "closed": "Open", "protected": "No", "note": "Check latest local rules."},
    "Garrick / Leervis": {"bag": "2", "min_size": "70 cm", "closed": "Verify current season", "protected": "No", "note": "Regional rules may apply."},
    "Kob": {"bag": "Varies", "min_size": "Varies", "closed": "Verify local rules", "protected": "No", "note": "Kob limits vary by species and area."},
    "Shad / Elf": {"bag": "4", "min_size": "30 cm", "closed": "Seasonal closure applies", "protected": "No", "note": "Verify current closure before keeping."},
    "Spotted Grunter": {"bag": "5", "min_size": "40 cm", "closed": "Open", "protected": "No", "note": "Verify current local rules."},
    "Pompano": {"bag": "10", "min_size": "None / verify", "closed": "Open", "protected": "No", "note": "Verify species-specific rules."},
    "White Steenbras": {"bag": "1", "min_size": "60 cm", "closed": "Verify", "protected": "No", "note": "High-risk species; verify current law."},
    "Sand Steenbras": {"bag": "5", "min_size": "40 cm", "closed": "Open", "protected": "No", "note": "Verify current local rules."},
    "Galjoen": {"bag": "2", "min_size": "35 cm", "closed": "Seasonal closure applies", "protected": "No", "note": "SA national fish; verify season."},
    "White Musselcracker": {"bag": "1", "min_size": "60 cm", "closed": "Verify", "protected": "No", "note": "Verify latest rules."},
    "Kingfish": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "No", "note": "Species-specific rules apply."},
    "Grey Shark": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "No", "note": "Catch-and-release recommended unless sure."},
    "Sand Shark": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "No", "note": "Catch-and-release recommended unless sure."},
    "Spotted Gully Shark": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "No", "note": "Catch-and-release recommended unless sure."},
}


# =====================================================
# Fishing spot library + fallback profiles
# =====================================================

FISHING_SPOTS = {
    "Leisure Bay Main Beach Gully": {
        "area": "Leisure Bay", "stand": (-30.823900, 30.406200), "parking": (-30.823400, 30.405750),
        "structure": "Dark sand gully with white-water edge", "feature_type": "gully", "base_confidence": 78,
        "species": ["Kob", "Shad / Elf", "Bronze Bream", "Blacktail", "Sand Shark", "Grey Shark"],
        "notes": "Fish the edge where white water meets the darker channel.",
        "parking_note": "Use public beach access/parking where permitted.",
    },
    "Trafalgar Rock-Sand Transition": {
        "area": "Trafalgar", "stand": (-30.833900, 30.410500), "parking": (-30.833350, 30.409850),
        "structure": "Rock and sand transition with feeding gully", "feature_type": "gully", "base_confidence": 82,
        "species": ["Kob", "Shad / Elf", "Bronze Bream", "Blacktail", "Grey Shark"],
        "notes": "Target the gully edge, not the middle.",
        "parking_note": "Park at legal beach access and walk down to the rock/sand transition.",
    },
    "Palm Beach White-Water Channel": {
        "area": "Palm Beach", "stand": (-30.867000, 30.382300), "parking": (-30.866450, 30.381850),
        "structure": "Working white water with channel edge", "feature_type": "white water", "base_confidence": 74,
        "species": ["Shad / Elf", "Kob", "Garrick / Leervis", "Bronze Bream", "Blacktail", "Pompano"],
        "notes": "Good when the water is working and not too clean.",
        "parking_note": "Use public beach parking/access.",
    },
    "Southbroom River-Mouth Channel": {
        "area": "Southbroom", "stand": (-30.919200, 30.328700), "parking": (-30.918700, 30.328100),
        "structure": "River-mouth influence with deeper channel", "feature_type": "river mouth", "base_confidence": 76,
        "species": ["Kob", "Garrick / Leervis", "Spotted Grunter", "Pompano", "Shad / Elf"],
        "notes": "Better around moving tide; fish the channel seam.",
        "parking_note": "Park near public river-mouth/beach access where permitted.",
    },
    "Umhlanga Lighthouse Gully": {
        "area": "Umhlanga", "stand": (-29.717820, 31.089420), "parking": (-29.717250, 31.088450),
        "structure": "Deep gully near lighthouse rocks", "feature_type": "gully", "base_confidence": 80,
        "species": ["Kob", "Garrick / Leervis", "Shad / Elf", "Blacktail", "Bronze Bream", "Kingfish"],
        "notes": "Use caution on rocks; fish the gully edge.",
        "parking_note": "Park at legal promenade/beach access.",
    },
    "Umhlanga Lagoon Mouth Current Seam": {
        "area": "Umhlanga", "stand": (-29.720500, 31.088000), "parking": (-29.721000, 31.087400),
        "structure": "River mouth current seam", "feature_type": "river mouth", "base_confidence": 82,
        "species": ["Garrick / Leervis", "Kob", "Spotted Grunter", "Shad / Elf", "Pompano"],
        "notes": "Best on pushing or outgoing tide.",
        "parking_note": "Use safe lagoon/beach access and avoid isolated areas.",
    },
    "Bronze Beach Gully Section": {
        "area": "Umhlanga", "stand": (-29.713900, 31.092000), "parking": (-29.713400, 31.091350),
        "structure": "Sandbank drop-off with working white water", "feature_type": "white water", "base_confidence": 76,
        "species": ["Shad / Elf", "Kob", "Garrick / Leervis", "Pompano", "Grey Shark"],
        "notes": "Good for shad when white water is active.",
        "parking_note": "Park at legal beach/promenade access.",
    },
    "Port Edward Rocky Point": {
        "area": "Port Edward", "stand": (-31.050700, 30.226400), "parking": (-31.050150, 30.225850),
        "structure": "Rocky point and gully water", "feature_type": "gully", "base_confidence": 80,
        "species": ["Kob", "Shad / Elf", "Bronze Bream", "Blacktail", "Grey Shark"],
        "notes": "Target white water and channel edges; be careful on rocks.",
        "parking_note": "Park at legal beach access and walk to safe standing area.",
    },
    "Ballito Tidal Pool Edge": {
        "area": "Ballito", "stand": (-29.538150, 31.218950), "parking": (-29.538650, 31.218250),
        "structure": "Rock/sand edge near tidal pool area", "feature_type": "gully", "base_confidence": 74,
        "species": ["Blacktail", "Bronze Bream", "Shad / Elf", "Kob", "Pompano"],
        "notes": "Scratch the rock/sand edges and watch the swell.",
        "parking_note": "Use public beach parking and obey access rules.",
    },
}

COAST_PROFILES = {
    "Umhlanga": {"sea": 105, "land": 285, "stand_inland_m": 35, "cast_m": 75},
    "Ballito": {"sea": 105, "land": 285, "stand_inland_m": 35, "cast_m": 75},
    "Port Edward": {"sea": 120, "land": 300, "stand_inland_m": 35, "cast_m": 75},
    "Leisure Bay": {"sea": 130, "land": 310, "stand_inland_m": 35, "cast_m": 75},
    "Trafalgar": {"sea": 125, "land": 305, "stand_inland_m": 35, "cast_m": 75},
    "Palm Beach": {"sea": 120, "land": 300, "stand_inland_m": 35, "cast_m": 75},
    "Southbroom": {"sea": 115, "land": 295, "stand_inland_m": 35, "cast_m": 75},
    "Durban": {"sea": 100, "land": 280, "stand_inland_m": 35, "cast_m": 75},
    "default_kzn": {"sea": 110, "land": 290, "stand_inland_m": 35, "cast_m": 75},
    "default_ec": {"sea": 135, "land": 315, "stand_inland_m": 35, "cast_m": 75},
    "default_wc": {"sea": 230, "land": 50, "stand_inland_m": 35, "cast_m": 75},
}


def profile_for_area(area: str, lat: float, lon: float) -> Dict[str, float]:
    for key, value in COAST_PROFILES.items():
        if key.lower() in str(area).lower():
            return value
    # rough regional fallback
    if lon > 30:
        return COAST_PROFILES["default_kzn"]
    if lon > 24:
        return COAST_PROFILES["default_ec"]
    return COAST_PROFILES["default_wc"]


# =====================================================
# Location search and coastline snapping
# =====================================================

@st.cache_data(ttl=API_CACHE_TTL_SECONDS)
def geocode_sa_location(query: str) -> Optional[Dict[str, Any]]:
    q = f"{query}, South Africa"
    data = safe_request_json(
        "https://nominatim.openstreetmap.org/search",
        params={"q": q, "format": "json", "limit": 5, "addressdetails": 1, "countrycodes": "za"},
        retries=1,
    )
    if not data:
        return None
    best = data[0]
    return {
        "lat": float(best["lat"]),
        "lon": float(best["lon"]),
        "display_name": best.get("display_name", query),
        "raw": best,
    }


@st.cache_data(ttl=API_CACHE_TTL_SECONDS)
def smart_location_suggestions(query: str) -> List[Dict[str, Any]]:
    """
    Coastal-biased suggestions.
    User can type 'Umhlanga' or 'Umhlanga Lighthouse'.
    App returns coastal options first and avoids inland duplicates where possible.
    """
    if not query or len(query.strip()) < 2:
        return []

    q = query.strip()
    search_variants = [
        f"{q} Beach, KwaZulu-Natal, South Africa",
        f"{q} Lighthouse, KwaZulu-Natal, South Africa",
        f"{q} Lagoon, KwaZulu-Natal, South Africa",
        f"{q} Rocks, KwaZulu-Natal, South Africa",
        f"{q}, eThekwini, KwaZulu-Natal, South Africa",
        f"{q}, KwaZulu-Natal, South Africa",
        f"{q}, South Africa",
    ]

    # Known coastal aliases to make common inputs work immediately
    known_aliases = {
        "umhlanga": [
            {"lat": -29.717820, "lon": 31.089420, "display_name": "Umhlanga Lighthouse, Umhlanga, KwaZulu-Natal"},
            {"lat": -29.713900, "lon": 31.092000, "display_name": "Bronze Beach, Umhlanga, KwaZulu-Natal"},
            {"lat": -29.720500, "lon": 31.088000, "display_name": "Umhlanga Lagoon Mouth, KwaZulu-Natal"},
            {"lat": -29.724000, "lon": 31.086800, "display_name": "Umhlanga Rocks Beach, KwaZulu-Natal"},
        ],
        "ballito": [
            {"lat": -29.538150, "lon": 31.218950, "display_name": "Ballito Tidal Pool / Beach, KwaZulu-Natal"},
            {"lat": -29.526500, "lon": 31.223200, "display_name": "Willard Beach, Ballito, KwaZulu-Natal"},
        ],
        "port edward": [
            {"lat": -31.050700, "lon": 30.226400, "display_name": "Port Edward Rocky Point / Beach, KwaZulu-Natal"},
        ],
        "trafalgar": [
            {"lat": -30.833900, "lon": 30.410500, "display_name": "Trafalgar Beach, KwaZulu-Natal"},
        ],
        "southbroom": [
            {"lat": -30.919200, "lon": 30.328700, "display_name": "Southbroom River Mouth, KwaZulu-Natal"},
        ],
    }

    suggestions = []
    q_lower = q.lower()
    for key, vals in known_aliases.items():
        if q_lower == key or key in q_lower or q_lower in key:
            suggestions.extend(vals)

    seen = set()
    for variant in search_variants:
        data = safe_request_json(
            "https://nominatim.openstreetmap.org/search",
            params={"q": variant, "format": "json", "limit": 4, "addressdetails": 1, "countrycodes": "za"},
            retries=1,
        )
        if not data:
            continue
        for item in data:
            try:
                lat = float(item["lat"])
                lon = float(item["lon"])
            except Exception:
                continue

            display = item.get("display_name", variant)

            # Coastal bias:
            # Avoid obvious inland results when a coastal option exists.
            # KZN coast longitudes are usually ~30.2 to 31.3.
            # This filter is intentionally loose to support SA-wide coastal searches.
            if lon < 18 or lon > 33 or lat < -35 or lat > -22:
                continue

            key = (round(lat, 5), round(lon, 5), display[:60])
            if key in seen:
                continue
            seen.add(key)

            coastal_words = ["beach", "lighthouse", "lagoon", "rocks", "mouth", "coast", "harbour", "bay", "strand"]
            score = 0
            disp_l = display.lower()
            if any(w in disp_l for w in coastal_words):
                score += 20
            if "kwazulu-natal" in disp_l or "ethekwini" in disp_l:
                score += 10
            # Prefer results near the sea in KZN/EC/WC instead of inland same-name towns
            if lon >= 28:
                score += 5

            suggestions.append({"lat": lat, "lon": lon, "display_name": display, "score": score})

    # De-duplicate again and rank
    clean = []
    seen2 = set()
    for s in suggestions:
        key = (round(s["lat"], 4), round(s["lon"], 4))
        if key in seen2:
            continue
        seen2.add(key)
        clean.append(s)

    clean.sort(key=lambda x: x.get("score", 0), reverse=True)
    return clean[:8]


def selected_location_from_suggestions(query: str) -> Optional[Dict[str, Any]]:
    suggestions = smart_location_suggestions(query)
    if not suggestions:
        return geocode_sa_location(query)

    labels = [s["display_name"] for s in suggestions]
    selected_label = st.sidebar.selectbox("Select your fishing area", labels)
    selected = suggestions[labels.index(selected_label)]
    return {
        "lat": selected["lat"],
        "lon": selected["lon"],
        "display_name": selected["display_name"],
        "raw": selected,
    }


@st.cache_data(ttl=API_CACHE_TTL_SECONDS)
def overpass_coastal_features(lat: float, lon: float, radius_m: int = 9000) -> List[Dict[str, Any]]:
    """
    Finds beach/coast related OSM features near a point.
    We use this for dynamic ranked coastal options and approximate coastline points.
    """
    query = f"""
    [out:json][timeout:15];
    (
      node(around:{radius_m},{lat},{lon})["natural"~"beach|coastline|bay"];
      way(around:{radius_m},{lat},{lon})["natural"~"beach|coastline|bay"];
      relation(around:{radius_m},{lat},{lon})["natural"~"beach|coastline|bay"];
      node(around:{radius_m},{lat},{lon})["place"~"beach|locality"];
      node(around:{radius_m},{lat},{lon})["tourism"="beach"];
    );
    out center tags 80;
    """
    data = safe_request_json("https://overpass-api.de/api/interpreter", params={"data": query}, timeout=20, retries=0)
    if not data or "elements" not in data:
        return []

    features = []
    seen = set()
    for el in data["elements"]:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("natural") or tags.get("place") or "Coastal option"
        if "lat" in el and "lon" in el:
            flat, flon = float(el["lat"]), float(el["lon"])
        elif "center" in el:
            flat, flon = float(el["center"]["lat"]), float(el["center"]["lon"])
        else:
            continue
        key = (round(flat, 5), round(flon, 5), name)
        if key in seen:
            continue
        seen.add(key)
        features.append({
            "name": name,
            "lat": flat,
            "lon": flon,
            "tags": tags,
            "type": tags.get("natural") or tags.get("tourism") or tags.get("place") or "coastal",
        })
    features.sort(key=lambda f: haversine_km(lat, lon, f["lat"], f["lon"]))
    return features[:30]


def snap_point_to_coast(
    planning_point: Tuple[float, float],
    area_name: str,
    preferred_point: Optional[Tuple[float, float]] = None,
) -> Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], Dict[str, Any]]:
    """
    Returns parking/access-ish point, stand point, cast point, metadata.
    The strongest version would use polygons for land/water. This app uses:
    - OSM coastal feature if available
    - Area profile fallback if OSM unavailable
    - Stand is pulled landward from coastline point
    - Cast is pushed seaward from coastline point
    """
    lat, lon = preferred_point if preferred_point else planning_point
    profile = profile_for_area(area_name, lat, lon)

    # Try OSM coastal feature nearest to the spot/planning location
    osm_features = overpass_coastal_features(planning_point[0], planning_point[1], radius_m=10000)
    coast_point = (lat, lon)
    coast_source = "Stored spot / fallback profile"

    if osm_features:
        nearest = min(osm_features, key=lambda f: distance_km(planning_point, (f["lat"], f["lon"])))
        # Only use OSM point if it is reasonably close to the planning point
        if distance_km(planning_point, (nearest["lat"], nearest["lon"])) <= 10:
            coast_point = (nearest["lat"], nearest["lon"])
            coast_source = f"OSM coastal feature: {nearest['name']}"

    land_bearing = profile["land"]
    sea_bearing = profile["sea"]
    stand = destination_point(coast_point, land_bearing, profile["stand_inland_m"])
    cast = destination_point(coast_point, sea_bearing, profile["cast_m"])
    parking = destination_point(stand, land_bearing, 250)

    return parking, stand, cast, {
        "coast_source": coast_source,
        "sea_bearing": sea_bearing,
        "land_bearing": land_bearing,
        "stand_inland_m": profile["stand_inland_m"],
        "cast_m": profile["cast_m"],
        "coast_point": coast_point,
    }


# =====================================================
# API: weather, marine, tide
# =====================================================

@st.cache_data(ttl=API_CACHE_TTL_SECONDS)
def fetch_conditions(lat, lon, trip_date_str, bucket):
    target_hour = TIME_BUCKET_HOUR.get(bucket, 12)
    result = {"available": False, "weather_error": None, "marine_error": None}
    try:
        w = safe_request_json(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m,wind_direction_10m,pressure_msl,cloud_cover",
                "timezone": "auto",
                "forecast_days": 10,
            },
            retries=1,
        )
        times = w.get("hourly", {}).get("time", []) if w else []
        idx = next((i for i, t in enumerate(times) if t.startswith(trip_date_str) and int(t[11:13]) == target_hour), 0 if times else None)
        if idx is not None:
            h = w["hourly"]
            result.update({
                "available": True,
                "temperature": h["temperature_2m"][idx],
                "rain_probability": h["precipitation_probability"][idx],
                "weather_code": h["weather_code"][idx],
                "wind_speed": h["wind_speed_10m"][idx],
                "wind_direction": h["wind_direction_10m"][idx],
                "pressure": h["pressure_msl"][idx],
                "cloud_cover": h["cloud_cover"][idx],
            })
    except Exception as e:
        result["weather_error"] = f"Weather API issue: {e}"

    try:
        m = safe_request_json(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "wave_height,wave_period,wave_direction,sea_surface_temperature",
                "timezone": "auto",
                "forecast_days": 10,
            },
            retries=1,
        )
        times = m.get("hourly", {}).get("time", []) if m else []
        idx = next((i for i, t in enumerate(times) if t.startswith(trip_date_str) and int(t[11:13]) == target_hour), 0 if times else None)
        if idx is not None:
            h = m["hourly"]
            result.update({
                "wave_height": h["wave_height"][idx],
                "wave_period": h["wave_period"][idx],
                "wave_direction": h["wave_direction"][idx],
                "sea_temp": h["sea_surface_temperature"][idx],
            })
    except Exception as e:
        result["marine_error"] = f"Marine API issue: {e}"

    return result


def infer_tide_stage(extremes):
    if not extremes or len(extremes) < 2:
        return None
    first = str(extremes[0].get("type", "")).lower()
    second = str(extremes[1].get("type", "")).lower()
    if "low" in first and "high" in second:
        return "Pushing tide"
    if "high" in first and "low" in second:
        return "Outgoing tide"
    return None


@st.cache_data(ttl=API_CACHE_TTL_SECONDS)
def fetch_worldtides(lat, lon, trip_date_str, key):
    if not key:
        return {"available": False, "source": "WorldTides", "status": "No WORLD_TIDES_API_KEY configured.", "next_tides": [], "stage": None}
    data = safe_request_json(
        "https://www.worldtides.info/api/v3",
        params={"extremes": "", "heights": "", "lat": lat, "lon": lon, "date": trip_date_str, "days": 1, "key": key},
        retries=1,
    )
    if not data:
        return {"available": False, "source": "WorldTides", "status": "WorldTides failed or timed out.", "next_tides": [], "stage": None}
    extremes = data.get("extremes", [])
    return {"available": bool(extremes), "source": "WorldTides", "status": "WorldTides loaded." if extremes else "WorldTides returned no tide extremes.", "next_tides": extremes[:6], "stage": infer_tide_stage(extremes)}


@st.cache_data(ttl=API_CACHE_TTL_SECONDS)
def fetch_stormglass(lat, lon, trip_date_str, key):
    if not key:
        return {"available": False, "source": "Stormglass", "status": "No STORMGLASS_API_KEY configured.", "next_tides": [], "stage": None}
    start = datetime.fromisoformat(trip_date_str)
    end = start + timedelta(days=1)
    data = safe_request_json(
        "https://api.stormglass.io/v2/tide/extremes/point",
        params={"lat": lat, "lng": lon, "start": start.isoformat(), "end": end.isoformat()},
        headers={"Authorization": key},
        retries=1,
    )
    if not data:
        return {"available": False, "source": "Stormglass", "status": "Stormglass failed or timed out.", "next_tides": [], "stage": None}
    extremes = data.get("data", [])
    return {"available": bool(extremes), "source": "Stormglass", "status": "Stormglass tide extremes loaded." if extremes else "Stormglass returned no tide extremes.", "next_tides": extremes[:6], "stage": infer_tide_stage(extremes)}


def estimate_tide_stage(bucket: str, moon: str) -> str:
    # Fallback only; avoids asking user to guess.
    if bucket in ["Early Morning", "Evening", "Night"]:
        return "Estimated moving tide"
    if moon in ["New Moon", "Full Moon"]:
        return "Estimated stronger tide movement"
    return "Estimated tide / verify locally"


def get_tide_data(lat, lon, trip_date_str, bucket, moon):
    wt = fetch_worldtides(lat, lon, trip_date_str, WORLD_TIDES_API_KEY)
    if wt["available"]:
        return wt
    sg = fetch_stormglass(lat, lon, trip_date_str, STORMGLASS_API_KEY)
    if sg["available"]:
        return sg
    return {
        "available": False,
        "source": "Estimated tide",
        "status": "No live tide API loaded. Using estimated tide logic; verify locally.",
        "next_tides": [],
        "stage": estimate_tide_stage(bucket, moon),
    }


# =====================================================
# Bait, target, confidence engine — SINGLE SOURCE OF TRUTH
# =====================================================

def bait_match_engine(available_baits: List[str], ideal_baits: List[str]):
    if not available_baits:
        return "No bait selected", [], "No bait selected. Add your available bait for a better recommendation."

    matched = [b for b in available_baits if b in ideal_baits]
    if matched:
        return "Good match", matched, f"Good match: your bait ({', '.join(matched)}) suits this target."

    return "Poor match", [], f"Your selected bait ({', '.join(available_baits)}) is not ideal for this target."


def suggest_species_for_bait(available_baits: List[str], candidate_species: List[str]) -> Optional[str]:
    if not available_baits:
        return None
    scored = []
    for fish in candidate_species:
        if fish not in SPECIES:
            continue
        status, matched, _ = bait_match_engine(available_baits, SPECIES[fish]["ideal_baits"])
        score = len(matched) * 20
        if status == "Good match":
            score += 20
        scored.append((fish, score))
    scored = [x for x in scored if x[1] > 0]
    if not scored:
        return None
    return sorted(scored, key=lambda x: x[1], reverse=True)[0][0]


def condition_score_engine(conditions, tide_stage, moon_phase, species, bucket):
    score, pos, neg = 50, [], []

    if tide_stage in ["Pushing tide", "Outgoing tide", "Estimated moving tide", "Estimated stronger tide movement"]:
        score += 10
        pos.append("Moving tide / expected movement supports feeding.")
    elif tide_stage in ["High tide turning", "Low tide turning"]:
        score += 5
        pos.append("Turning tide can trigger short feeding windows.")
    else:
        score -= 2
        neg.append("Tide confidence is limited.")

    if moon_phase in ["New Moon", "Full Moon"]:
        score += 6
        pos.append("New/full moon may increase tidal movement.")

    wind = conditions.get("wind_speed")
    wave = conditions.get("wave_height")
    period = conditions.get("wave_period")
    rain = conditions.get("rain_probability")

    if wind is not None:
        if wind <= 25:
            score += 8
            pos.append("Wind speed appears fishable.")
        elif wind <= 40:
            score -= 2
            neg.append("Wind may make casting harder.")
        else:
            score -= 10
            neg.append("Strong wind may be difficult or unsafe.")

    if wave is not None:
        if 0.7 <= wave <= 1.8:
            score += 10
            pos.append("Swell height may create working water.")
        elif wave < 0.7:
            score -= 3
            neg.append("Sea may be too flat.")
        else:
            score -= 8
            neg.append("Swell may be rough; check safety.")

    if period is not None:
        if 8 <= period <= 14:
            score += 5
            pos.append("Wave period supports structured surf movement.")
        elif period > 16:
            score -= 4
            neg.append("Long-period swell can create powerful sets.")

    if rain is not None and rain >= 70:
        score -= 5
        neg.append("High rain probability may reduce comfort.")

    if species in SPECIES and bucket in SPECIES[species]["time_bonus"]:
        score += 7
        pos.append(f"{bucket} suits {species}.")

    return max(0, min(95, int(score))), pos, neg


def final_confidence_engine(
    spot: Dict[str, Any],
    selected_species: str,
    available_baits: List[str],
    time_bucket: str,
    condition_score: int,
    distance_from_planning_km: float,
) -> Tuple[int, Dict[str, Any]]:
    """
    One confidence engine used by BOTH:
    - ranked recommendation table/cards
    - loaded recommendation card
    """
    raw = int(spot.get("base_confidence", spot.get("confidence", 70)))
    detail = {"base": raw, "adjustments": []}

    feature_type = spot.get("feature_type", "")
    if feature_type in ["gully", "river mouth", "white water"]:
        raw += 6
        detail["adjustments"].append("+6 structure")

    if selected_species in spot.get("species", []):
        raw += 5
        detail["adjustments"].append("+5 target known at spot")
    else:
        raw -= 6
        detail["adjustments"].append("-6 target less typical at spot")

    if selected_species in SPECIES and time_bucket in SPECIES[selected_species]["time_bonus"]:
        raw += 6
        detail["adjustments"].append("+6 time suits species")
    else:
        raw -= 2
        detail["adjustments"].append("-2 time less ideal")

    if selected_species in SPECIES:
        bait_status, matched, _ = bait_match_engine(available_baits, SPECIES[selected_species]["ideal_baits"])
        if bait_status == "Good match":
            raw += 7
            detail["adjustments"].append("+7 bait match")
        elif bait_status == "Poor match":
            raw -= 12
            detail["adjustments"].append("-12 bait mismatch")

    if distance_from_planning_km <= 2:
        raw += 4
        detail["adjustments"].append("+4 close")
    elif distance_from_planning_km <= 10:
        raw += 2
        detail["adjustments"].append("+2 nearby")
    elif distance_from_planning_km > 30:
        raw -= 5
        detail["adjustments"].append("-5 far")

    # Blend with live conditions; do it here only.
    final = int((raw * 0.62) + (condition_score * 0.38))
    final = max(0, min(95, final))
    detail["raw_spot_potential"] = max(0, min(95, raw))
    detail["condition_score"] = condition_score
    detail["final"] = final
    return final, detail


def choose_target_species(preferred_target, likely_species, available_baits):
    """
    If bait does not suit preferred target, switch to best target for bait and tell user.
    """
    likely_species = [f for f in likely_species if f in SPECIES]
    if not likely_species:
        likely_species = ["Kob"]

    if preferred_target == "Auto select":
        bait_based = suggest_species_for_bait(available_baits, likely_species)
        if bait_based:
            return bait_based, None
        return likely_species[0], None

    chosen = preferred_target
    if chosen not in SPECIES:
        return likely_species[0], f"{chosen} is not fully configured yet. Using {likely_species[0]}."

    status, matched, msg = bait_match_engine(available_baits, SPECIES[chosen]["ideal_baits"])
    if available_baits and status == "Poor match":
        alt = suggest_species_for_bait(available_baits, likely_species)
        if alt and alt != chosen:
            return alt, (
                f"You selected **{chosen}**, but your bait (**{', '.join(available_baits)}**) is not ideal for {chosen}. "
                f"Based on your bait and this spot, CastIQ recommends **{alt}** instead."
            )

    return chosen, None


def build_osm_dynamic_spots(planning_point, radius_km, known_names) -> Dict[str, Dict[str, Any]]:
    features = overpass_coastal_features(planning_point[0], planning_point[1], radius_m=int(radius_km * 1000))
    dynamic = {}
    for f in features:
        name = f"{f['name']} (OSM coastal option)"
        if name in known_names:
            continue
        d = distance_km(planning_point, (f["lat"], f["lon"]))
        if d > radius_km:
            continue
        # Avoid too many generic duplicates
        base_species = ["Kob", "Shad / Elf", "Garrick / Leervis", "Blacktail", "Pompano"]
        dynamic[name] = {
            "area": f["name"],
            "stand": (f["lat"], f["lon"]),
            "parking": destination_point((f["lat"], f["lon"]), 290, 250),
            "structure": "OpenStreetMap coastal feature near selected location",
            "feature_type": "white water" if f.get("type") == "beach" else "coastal",
            "base_confidence": 72 if f.get("type") == "beach" else 68,
            "species": base_species,
            "notes": "Dynamic OSM coastal option. Validate access, safety and water before fishing.",
            "parking_note": "Use nearest legal public access/parking.",
            "osm_generated": True,
        }
    return dynamic


def build_ranked_recommendations(planning_point, radius_km, preferred_target, available_baits, time_bucket, trip_date):
    all_spots = dict(FISHING_SPOTS)
    dynamic = build_osm_dynamic_spots(planning_point, radius_km, set(all_spots.keys()))
    all_spots.update(dynamic)

    rows = []
    detailed = {}

    for name, spot in all_spots.items():
        d = distance_km(planning_point, spot["stand"])
        if d > radius_km:
            continue

        selected_species, bait_warning = choose_target_species(preferred_target, spot["species"], available_baits)

        # Use snapped stand/cast for condition lookup where possible
        parking, stand, cast, coast_meta = snap_point_to_coast(planning_point, spot["area"], spot.get("stand"))

        conditions = fetch_conditions(stand[0], stand[1], trip_date.strftime("%Y-%m-%d"), time_bucket)
        moon = moon_phase_name(trip_date)
        tide = get_tide_data(stand[0], stand[1], trip_date.strftime("%Y-%m-%d"), time_bucket, moon)
        condition_score, cond_pos, cond_neg = condition_score_engine(conditions, tide["stage"], moon, selected_species, time_bucket)
        final_score, score_detail = final_confidence_engine(spot, selected_species, available_baits, time_bucket, condition_score, d)

        rows.append({
            "Spot": name,
            "Area": spot["area"],
            "Distance km": round(d, 2),
            "Fishing confidence": final_score,
            "Confidence range": confidence_label(final_score),
            "Spot potential": score_detail["raw_spot_potential"],
            "Suggested target": selected_species,
            "Structure": spot["structure"],
        })

        detailed[name] = {
            "name": name,
            "spot": spot,
            "distance_km": d,
            "selected_species": selected_species,
            "bait_warning": bait_warning,
            "parking": parking,
            "stand": stand,
            "cast": cast,
            "coast_meta": coast_meta,
            "conditions": conditions,
            "tide": tide,
            "moon": moon,
            "condition_score": condition_score,
            "cond_pos": cond_pos,
            "cond_neg": cond_neg,
            "final_confidence": final_score,
            "score_detail": score_detail,
        }

    df = pd.DataFrame(rows)
    if df.empty:
        return df, detailed

    df = df.sort_values(["Fishing confidence", "Distance km"], ascending=[False, True]).reset_index(drop=True)
    return df, detailed



# =====================================================
# Auto test engine
# =====================================================

def auto_test_one_location(test_location: str, test_bait: List[str], test_target: str, test_radius_km: int = 20) -> List[Dict[str, Any]]:
    """
    Runs app-level health checks without needing the user to manually inspect every screen.
    Returns a list of test result dictionaries.
    """
    results = []

    def add(check, status, detail):
        results.append({
            "Location": test_location,
            "Check": check,
            "Status": status,
            "Detail": detail,
        })

    try:
        found = geocode_sa_location(test_location)
        if not found:
            add("Location search", "FAIL", "Nominatim could not find location.")
            return results

        planning = (found["lat"], found["lon"])
        add("Location search", "PASS", f"Found {found['display_name']}")

        df, detail_map = build_ranked_recommendations(
            planning_point=planning,
            radius_km=float(test_radius_km),
            preferred_target=test_target,
            available_baits=test_bait,
            time_bucket="Evening",
            trip_date=datetime.today().date(),
        )

        if df.empty:
            add("Ranked recommendations", "FAIL", "No recommendations returned.")
            return results

        add("Ranked recommendations", "PASS", f"{len(df)} options returned.")

        top = df.iloc[0]
        selected_name = top["Spot"]
        loaded = detail_map.get(selected_name)

        if not loaded:
            add("Loaded recommendation exists", "FAIL", "Top ranked spot missing from detailed map.")
            return results

        add("Loaded recommendation exists", "PASS", selected_name)

        table_conf = int(top["Fishing confidence"])
        loaded_conf = int(loaded["final_confidence"])
        if table_conf == loaded_conf:
            add("Confidence match", "PASS", f"Table {table_conf}% = loaded {loaded_conf}%")
        else:
            add("Confidence match", "FAIL", f"Table {table_conf}% != loaded {loaded_conf}%")

        stand = loaded["stand"]
        cast = loaded["cast"]
        parking = loaded["parking"]

        valid_coords = (
            -35 <= stand[0] <= -22 and 16 <= stand[1] <= 33 and
            -35 <= cast[0] <= -22 and 16 <= cast[1] <= 33 and
            -35 <= parking[0] <= -22 and 16 <= parking[1] <= 33
        )
        add("Coordinate validity", "PASS" if valid_coords else "FAIL", f"Parking={parking}, Stand={stand}, Cast={cast}")

        stand_planning_distance = distance_m(planning, stand)
        if stand_planning_distance > 25:
            add("Stand not identical to planning point", "PASS", f"Stand is {int(stand_planning_distance)}m from planning point.")
        else:
            add("Stand not identical to planning point", "WARN", f"Stand only {int(stand_planning_distance)}m from planning point. May be okay if searched exact beach.")

        cast_distance = distance_m(stand, cast)
        if 30 <= cast_distance <= 180:
            add("Cast distance realistic", "PASS", f"{int(cast_distance)}m")
        else:
            add("Cast distance realistic", "FAIL", f"{int(cast_distance)}m outside expected range.")

        parking_distance = distance_m(parking, stand)
        if 50 <= parking_distance <= 1500:
            add("Parking point exists", "PASS", f"Parking is {int(parking_distance)}m from stand.")
        else:
            add("Parking point exists", "WARN", f"Parking is {int(parking_distance)}m from stand; check access practicality.")

        species_after_logic = loaded["selected_species"]
        if test_target != "Auto select" and test_bait:
            original_status, _, _ = bait_match_engine(test_bait, SPECIES[test_target]["ideal_baits"])
            if original_status == "Poor match" and species_after_logic != test_target:
                add("Bait mismatch override", "PASS", f"{test_target} changed to {species_after_logic}")
            elif original_status == "Poor match" and species_after_logic == test_target:
                add("Bait mismatch override", "WARN", f"{test_target} remained selected despite bait mismatch.")
            else:
                add("Bait mismatch override", "PASS", "Original bait matched target.")

        conditions = loaded["conditions"]
        if conditions.get("available"):
            add("Weather/marine API", "PASS", "Open-Meteo returned weather data.")
        else:
            add("Weather/marine API", "WARN", "Weather unavailable, but app did not crash.")

        tide = loaded["tide"]
        if tide.get("available"):
            add("Tide API", "PASS", f"{tide['source']} loaded.")
        else:
            add("Tide fallback", "PASS", f"Fallback used: {tide['source']}")

        return results

    except Exception as e:
        add("Auto test exception", "FAIL", str(e))
        return results


def run_auto_tests() -> pd.DataFrame:
    test_locations = ["Umhlanga", "Ballito", "Port Edward", "Trafalgar", "Southbroom"]
    all_results = []
    for loc in test_locations:
        all_results.extend(auto_test_one_location(
            test_location=loc,
            test_bait=["Mackerel"],
            test_target="Bronze Bream",
            test_radius_km=20,
        ))
    return pd.DataFrame(all_results)


# =====================================================
# UI styling helpers
# =====================================================

st.markdown("""
<style>
    .main-title {
        font-size: 2.3rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }
    .hero-card {
        border: 1px solid #e5e7eb;
        border-radius: 22px;
        padding: 22px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.06);
        background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
        margin-bottom: 18px;
    }
    .mini-card {
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 16px;
        background: #ffffff;
        box-shadow: 0 4px 14px rgba(0,0,0,0.04);
        min-height: 150px;
    }
    .pill {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        background: #eef2ff;
        margin-right: 6px;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)


# =====================================================
# Sidebar
# =====================================================

st.sidebar.title("📍 Choose Your Fishing Area")
st.sidebar.caption("Search is recommended. Current/device location can be approximate.")

device_mode = st.sidebar.radio("How would you like to set your location?", ["🔎 Search location (recommended)", "📍 Use my current location (best on mobile)", "💻 Use my device location (approximate)"], index=0)

location_basis = "Manual search"
planning_point = None

if device_mode in ["📍 Use my current location (best on mobile)", "💻 Use my device location (approximate)"]:
    st.sidebar.info("GPS is best on mobile. Laptop GPS is often unavailable or inaccurate.")
    if streamlit_geolocation:
        loc = streamlit_geolocation()
        if loc and loc.get("latitude") is not None and loc.get("longitude") is not None:
            planning_point = (float(loc["latitude"]), float(loc["longitude"]))
            location_basis = "Live GPS"
            st.sidebar.success(f"GPS loaded: {planning_point[0]:.6f}, {planning_point[1]:.6f}")
        else:
            st.sidebar.warning("GPS not available. Use search below.")
    else:
        st.sidebar.warning("streamlit-geolocation not installed. Use search mode.")

search_query = st.sidebar.text_input("Search for a fishing area", value="Umhlanga", help="Examples: Umhlanga, Umhlanga Lighthouse, Ballito, Port Edward, Trafalgar Beach")

if planning_point is None:
    found = selected_location_from_suggestions(search_query) if search_query else None
    if found:
        planning_point = (found["lat"], found["lon"])
        location_basis = found["display_name"]
        st.sidebar.success(f"Using: {found['display_name']}")
    else:
        st.sidebar.error("Location not found. Try e.g. Umhlanga, Umhlanga Lighthouse, Ballito Beach, Port Edward Beach.")
        st.stop()

trip_date = st.sidebar.date_input("Fishing date", value=datetime.today())
time_bucket = st.sidebar.selectbox(
    "Preferred fishing time",
    options=list(TIME_BUCKET_WINDOWS.keys()),
    format_func=lambda x: f"{x} ({TIME_BUCKET_WINDOWS[x]})",
)
max_travel_km = st.sidebar.selectbox("Search radius", [2, 5, 10, 20, 50, 100], index=2)
available_baits = st.sidebar.multiselect("Bait you have available", ALL_BAITS, max_selections=10)
preferred_target = st.sidebar.selectbox("Preferred target species", ["Auto select"] + sorted(SPECIES.keys()))

with st.sidebar.expander("API status"):
    st.write("Open-Meteo: no key required")
    st.write("Nominatim/OSM: no key required")
    st.write(f"WorldTides key: {'Loaded' if WORLD_TIDES_API_KEY else 'Not configured'}")
    st.write(f"Stormglass key: {'Loaded' if STORMGLASS_API_KEY else 'Not configured'}")
    st.caption("No key = no crash. App uses fallback logic.")


# =====================================================
# Main
# =====================================================

st.markdown(f"<div class='main-title'>🎣 {APP_NAME}</div>", unsafe_allow_html=True)
st.caption("AI Fishing Intelligence: where to park, where to stand, where to cast, and what to use.")

show_dev_tools = st.sidebar.checkbox("🛠 Developer mode", value=False)

tab_names = [
    "🔥 Recommendation",
    "🛰️ Map & Navigation",
    "🎣 Beach Mode",
    "🌊 Conditions",
    "🎣 Bait & Trace",
    "📏 Regulations",
    "💎 Upgrade",
    "💬 Feedback",
]
if show_dev_tools:
    tab_names.append("🧪 Auto Test")

tabs = st.tabs(tab_names)

ranked_df, detailed = build_ranked_recommendations(
    planning_point=planning_point,
    radius_km=float(max_travel_km),
    preferred_target=preferred_target,
    available_baits=available_baits,
    time_bucket=time_bucket,
    trip_date=trip_date,
)

# Smart fallback:
# If the selected radius returns no options, do not block the user immediately.
# Automatically widen the search to 100 km so users searching a town/suburb
# still get the nearest coastal options.
auto_radius_used = max_travel_km
if ranked_df.empty:
    ranked_df, detailed = build_ranked_recommendations(
        planning_point=planning_point,
        radius_km=100.0,
        preferred_target=preferred_target,
        available_baits=available_baits,
        time_bucket=time_bucket,
        trip_date=trip_date,
    )
    auto_radius_used = 100
    if not ranked_df.empty:
        st.warning(
            f"No fishing options were found within your selected {max_travel_km} km radius. "
            "CastIQ automatically widened the search to 100 km and loaded the nearest coastal options."
        )

if ranked_df.empty:
    st.error(
        "No fishing options found. Try a more specific coastal search such as "
        "'Umhlanga Lighthouse', 'Bronze Beach', 'Ballito Beach', 'Port Edward Beach', or 'Trafalgar Beach'."
    )
    st.stop()

option_labels = [
    f"{row['Spot']} — {row['Fishing confidence']}% ({row['Confidence range']})"
    for _, row in ranked_df.iterrows()
]

if "selected_option_label" not in st.session_state or st.session_state.selected_option_label not in option_labels:
    st.session_state.selected_option_label = option_labels[0]

with tabs[0]:
    best_row = ranked_df.iloc[0]

    st.markdown("<div class='hero-card'>", unsafe_allow_html=True)
    h1, h2 = st.columns([2.3, 1])
    with h1:
        st.caption("BEST SPOT RIGHT NOW")
        st.header(str(best_row["Spot"]))
        st.write(f"**Area:** {best_row['Area']}")
        st.write(f"**Distance:** {best_row['Distance km']} km from planning point")
        st.write(f"**Suggested target:** {best_row['Suggested target']}")
        st.write(f"**Structure:** {best_row['Structure']}")
        st.markdown(
            f"<span class='pill'>Time: {time_bucket} ({TIME_BUCKET_WINDOWS[time_bucket]})</span>"
            f"<span class='pill'>Radius used: {auto_radius_used} km</span>"
            f"<span class='pill'>Planning: {search_query}</span>",
            unsafe_allow_html=True,
        )
    with h2:
        st.metric("Fishing confidence", f"{int(best_row['Fishing confidence'])}%")
        st.write(f"**Confidence level:** {best_row['Confidence range']}")
        st.write(f"**Spot potential:** {int(best_row['Spot potential'])}%")
    st.markdown("</div>", unsafe_allow_html=True)

    st.subheader("Ranked fishing options")
    st.caption("The table and loaded recommendation now use the same final live-adjusted confidence engine.")
    st.dataframe(ranked_df, use_container_width=True, hide_index=True)

    selected_label = st.selectbox(
        "Select the fishing option you want to load",
        option_labels,
        index=option_labels.index(st.session_state.selected_option_label),
    )
    st.session_state.selected_option_label = selected_label
    selected_name = selected_label.split(" — ")[0]
    loaded = detailed[selected_name]

    st.divider()
    col1, col2 = st.columns([2, 1])
    with col1:
        st.caption("Loaded recommendation")
        st.header(selected_name)
        st.write(f"**Area:** {loaded['spot']['area']}")
        st.write(f"**Why this spot:** {loaded['spot']['notes']}")
        st.write(f"**Coastline source:** {loaded['coast_meta']['coast_source']}")
        if loaded["bait_warning"]:
            st.warning(loaded["bait_warning"])
    with col2:
        st.metric("Fishing confidence", f"{loaded['final_confidence']}%")
        st.write(f"**Confidence level:** {confidence_label(loaded['final_confidence'])}")
        st.write(f"**Conditions score:** {loaded['condition_score']}%")
        st.write(f"**Spot potential:** {loaded['score_detail']['raw_spot_potential']}%")

    bearing = calculate_bearing(loaded["stand"], loaded["cast"])
    compass = bearing_to_compass(bearing)
    cast_distance = distance_m(loaded["stand"], loaded["cast"])
    st.success(
        f"{human_direction_text(compass)}\n\n"
        f"Cast towards: **{compass}**  \n"
        f"Bearing: **{int(bearing)}°**  \n"
        f"Distance: **±{int(cast_distance)} m**"
    )

    with st.expander("Why this confidence score?"):
        st.write("Adjustments:", ", ".join(loaded["score_detail"]["adjustments"]))
        st.write(loaded["score_detail"])


with tabs[1]:
    selected_name = st.session_state.selected_option_label.split(" — ")[0]
    loaded = detailed[selected_name]
    parking, stand, cast = loaded["parking"], loaded["stand"], loaded["cast"]
    bearing = calculate_bearing(stand, cast)
    compass = bearing_to_compass(bearing)
    cast_distance = distance_m(stand, cast)

    st.header("🛰️ Map & Navigation")
    nav1, nav2, nav3 = st.columns(3)

    drive_url = f"https://www.google.com/maps/dir/?api=1&origin={planning_point[0]},{planning_point[1]}&destination={parking[0]},{parking[1]}&travelmode=driving"
    walk_parking_url = f"https://www.google.com/maps/dir/?api=1&origin={parking[0]},{parking[1]}&destination={stand[0]},{stand[1]}&travelmode=walking"
    walk_current_url = f"https://www.google.com/maps/dir/?api=1&origin={planning_point[0]},{planning_point[1]}&destination={stand[0]},{stand[1]}&travelmode=walking"

    with nav1:
        st.link_button("🚗 Navigate to parking", drive_url, use_container_width=True)
    with nav2:
        st.link_button("🚶 Walk parking → stand", walk_parking_url, use_container_width=True)
    with nav3:
        st.link_button("📍 Walk current → stand", walk_current_url, use_container_width=True)

    st.info(
        f"Parking note: {loaded['spot'].get('parking_note', 'Use nearest legal public parking/access.')}\n\n"
        f"Then walk to the stand point and cast {int(cast_distance)}m towards {compass}."
    )

    if folium and st_folium:
        center = ((parking[0] + cast[0]) / 2, (parking[1] + cast[1]) / 2)
        m = folium.Map(location=center, zoom_start=16, tiles=None)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri World Imagery",
            name="Satellite",
        ).add_to(m)
        folium.Marker(planning_point, tooltip="Planning point", icon=folium.Icon(color="blue", icon="search", prefix="fa")).add_to(m)
        folium.Marker(parking, tooltip="Parking / access point", icon=folium.Icon(color="green", icon="car", prefix="fa")).add_to(m)
        folium.Marker(stand, tooltip="Stand here", icon=folium.DivIcon(html='<div style="font-size:34px;">🧍‍♂️</div>')).add_to(m)
        folium.Marker(cast, tooltip="Cast target", icon=folium.Icon(color="red", icon="bullseye", prefix="fa")).add_to(m)
        folium.PolyLine([parking, stand], color="green", weight=4, tooltip="Walk route").add_to(m)
        folium.PolyLine([stand, cast], color="blue", weight=5, tooltip=f"Cast {int(cast_distance)}m {compass}").add_to(m)
        folium.Circle(cast, radius=18, fill=True, tooltip="Bait landing zone").add_to(m)
        st_folium(m, width=1200, height=600)
    else:
        st.warning("Map packages not loaded. Install: pip install folium streamlit-folium")

    st.subheader("Voice-style directions")
    directions = [
        "Drive to the parking or access point first.",
        "Check that parking and beach access are legal and safe.",
        "Walk from the parking point towards the stand marker.",
        "Stop on safe dry sand or safe rock above the wash line.",
        human_direction_text(compass).replace(".", ""),
        f"Cast towards {compass}, bearing {int(bearing)} degrees, around {int(cast_distance)} metres.",
    ]
    for i, step in enumerate(directions, 1):
        st.write(f"**{i}.** {step}")


with tabs[2]:
    selected_name = st.session_state.selected_option_label.split(" — ")[0]
    loaded = detailed[selected_name]
    stand, cast = loaded["stand"], loaded["cast"]
    bearing = calculate_bearing(stand, cast)
    compass = bearing_to_compass(bearing)
    cast_distance = distance_m(stand, cast)

    st.header("🎣 On-the-Beach Mode")
    st.caption("Minimal action screen for when you are at the water.")

    b1, b2, b3 = st.columns(3)
    b1.metric("Target", loaded["selected_species"])
    b2.metric("Confidence", f"{loaded['final_confidence']}%")
    b3.metric("Cast", f"{compass} / {int(bearing)}°")

    st.success(
        f"📍 **Stand here:** {stand[0]:.6f}, {stand[1]:.6f}\n\n"
        f"➡️ **{human_direction_text(compass)}**\n\n"
        f"🎯 **Cast:** {compass} | {int(bearing)}° | ±{int(cast_distance)} m\n\n"
        f"🎣 **Use bait:** {', '.join(available_baits) if available_baits else 'Select bait in sidebar'}"
    )

    if loaded["cond_neg"]:
        st.warning("Watch-outs: " + " | ".join(loaded["cond_neg"]))
    if loaded["cond_pos"]:
        st.info("Positive signals: " + " | ".join(loaded["cond_pos"]))


with tabs[3]:
    selected_name = st.session_state.selected_option_label.split(" — ")[0]
    loaded = detailed[selected_name]
    c = loaded["conditions"]
    t = loaded["tide"]

    st.header("🌊 Conditions")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Weather")
        if c.get("available"):
            st.write(f"Temperature: {c.get('temperature')} °C")
            st.write(f"Weather: {weather_code_text(c.get('weather_code'))}")
            st.write(f"Rain probability: {c.get('rain_probability')}%")
            st.write(f"Pressure: {c.get('pressure')} hPa")
        else:
            st.warning("Weather unavailable")
        if c.get("weather_error"):
            st.warning(c["weather_error"])

    with col2:
        st.subheader("Wind + Marine")
        st.write(f"Wind: {c.get('wind_speed')} km/h from {direction_text(c.get('wind_direction'))}")
        st.write(f"Wave height: {c.get('wave_height')} m")
        st.write(f"Wave period: {c.get('wave_period')} sec")
        st.write(f"Sea temp: {c.get('sea_temp')} °C")
        if c.get("marine_error"):
            st.warning(c["marine_error"])

    with col3:
        st.subheader("Tide + Moon")
        st.write(f"Tide stage: {t['stage']}")
        st.write(f"Tide source: {t['source']}")
        st.caption(t["status"])
        st.write(f"Moon phase: {loaded['moon']}")
        st.metric("Conditions score", f"{loaded['condition_score']}%")

    if t.get("next_tides"):
        st.dataframe(pd.DataFrame(t["next_tides"]), use_container_width=True)
    if loaded["cond_pos"]:
        st.success("Positive signals: " + " | ".join(loaded["cond_pos"]))
    if loaded["cond_neg"]:
        st.warning("Caution signals: " + " | ".join(loaded["cond_neg"]))


with tabs[4]:
    selected_name = st.session_state.selected_option_label.split(" — ")[0]
    loaded = detailed[selected_name]
    fish = loaded["selected_species"]
    species = SPECIES[fish]
    bait_status, matched_baits, bait_message = bait_match_engine(available_baits, species["ideal_baits"])

    st.header("🎣 Bait & Trace")
    st.write(f"**Selected target:** {fish}")
    st.write(f"**Ideal bait:** {', '.join(species['ideal_baits'])}")
    st.write(f"**Bait you have:** {', '.join(available_baits) if available_baits else 'None selected'}")

    if bait_status == "Good match":
        st.success(bait_message)
    elif bait_status == "Poor match":
        st.warning(bait_message)
    else:
        st.info(bait_message)

    st.subheader("Recommended trace")
    st.write(f"**Trace:** {species['trace']}")
    st.code(species["trace_diagram"])

    st.subheader("Bite behaviour")
    st.write(f"**Bite style:** {species['bite_style']}")
    st.write(f"**Feel:** {species['feel']}")
    st.write(f"**Response:** {species['response']}")
    st.warning(f"Common mistake: {species['mistake']}")


with tabs[5]:
    selected_name = st.session_state.selected_option_label.split(" — ")[0]
    loaded = detailed[selected_name]
    fish = loaded["selected_species"]

    st.header("📏 Regulations")
    reg = REGULATIONS.get(fish)
    if reg:
        r1, r2, r3 = st.columns(3)
        r1.metric("Bag limit", reg["bag"])
        r2.metric("Minimum size", reg["min_size"])
        r3.metric("Protected", reg["protected"])
        st.write(f"Closed season: {reg['closed']}")
        st.info(reg["note"])
    else:
        st.warning("Regulation not loaded for this species yet.")

    st.dataframe(pd.DataFrame([{"Fish": f, **d} for f, d in REGULATIONS.items()]), use_container_width=True, hide_index=True)
    st.warning("Prototype regulation guide only. Verify current official regulations before keeping fish.")


with tabs[6]:
    st.header("💎 Choose Your Fishing Level")
    st.caption("Start simple, then upgrade when you want more precise fishing intelligence.")

    def package_card(image_path, title, persona, price, description, features, button_label):
        st.markdown("<div class='mini-card'>", unsafe_allow_html=True)
        if os.path.exists(image_path):
            st.image(image_path, use_container_width=True)
        else:
            st.info(f"Add image: {image_path}")
        st.subheader(title)
        st.caption(persona)
        st.markdown(f"### {price}")
        st.write(description)
        for feature in features:
            st.write(f"✅ {feature}")
        st.button(button_label, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)

    with col1:
        package_card(
            "assets/standard.jpg",
            "STANDARD 🎣",
            "Standard Fisherman",
            "R0",
            "Basic shoreline guidance for casual fishing sessions.",
            [
                "Search fishing areas",
                "Basic conditions view",
                "Simple recommendations",
            ],
            "Start Free",
        )

    with col2:
        package_card(
            "assets/pro.jpg",
            "PRO ⭐",
            "Pro Fisherman",
            "R49 / month",
            "Fish smarter with ranked options and guided decisions.",
            [
                "Exact stand and cast direction",
                "Bait and species matching",
                "Ranked fishing spots",
                "Parking to stand navigation",
            ],
            "Upgrade to Pro",
        )

    with col3:
        package_card(
            "assets/elite.jpg",
            "ELITE 🔥",
            "Elite Fisherman",
            "R99 / month",
            "Full real-time coastal intelligence for serious anglers.",
            [
                "Live/current location support",
                "Dynamic coastline engine",
                "On-the-Beach Mode",
                "Advanced condition scoring",
            ],
            "Go Elite",
        )

with tabs[7]:
    selected_name = st.session_state.selected_option_label.split(" — ")[0]
    loaded = detailed[selected_name]

    st.header("💬 Feedback / Accuracy Improvement")
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
                "location_basis": location_basis,
                "planning_lat": planning_point[0],
                "planning_lon": planning_point[1],
                "trip_date": str(trip_date),
                "time_bucket": time_bucket,
                "recommended_spot": selected_name,
                "target_species": loaded["selected_species"],
                "available_baits": ", ".join(available_baits),
                "result": result,
                "actual_species": actual_species,
                "actual_bait": actual_bait,
                "catch_outcome": catch_outcome,
                "comments": comments,
                "confidence": loaded["final_confidence"],
                "condition_score": loaded["condition_score"],
                "spot_potential": loaded["score_detail"]["raw_spot_potential"],
            }
            df_new = pd.DataFrame([feedback])
            try:
                df_old = pd.read_csv(FEEDBACK_FILE)
                df_all = pd.concat([df_old, df_new], ignore_index=True)
            except Exception:
                df_all = df_new
            df_all.to_csv(FEEDBACK_FILE, index=False)
            st.success("Feedback saved. This will support the future learning engine.")




if show_dev_tools:
    with tabs[8]:
        st.header("🧪 Auto Test")
        st.caption("Run this after every code change. It checks the main logic across common SA coastal locations.")

        st.info(
            "This test checks location search, ranked recommendations, confidence matching, "
            "parking/stand/cast coordinates, bait mismatch override, weather API, and tide fallback."
        )

        if st.button("Run Auto Test", use_container_width=True):
            with st.spinner("Running CastIQ auto tests..."):
                test_df = run_auto_tests()

            status_counts = test_df["Status"].value_counts().to_dict() if not test_df.empty else {}
            c1, c2, c3 = st.columns(3)
            c1.metric("PASS", status_counts.get("PASS", 0))
            c2.metric("WARN", status_counts.get("WARN", 0))
            c3.metric("FAIL", status_counts.get("FAIL", 0))

            if status_counts.get("FAIL", 0) > 0:
                st.error("Some tests failed. Review the table below and send a screenshot.")
            elif status_counts.get("WARN", 0) > 0:
                st.warning("No hard failures, but warnings need review.")
            else:
                st.success("All auto tests passed.")

            st.dataframe(test_df, use_container_width=True, hide_index=True)

            csv = test_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download test report CSV",
                data=csv,
                file_name="castiq_auto_test_report.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with st.expander("What PASS / WARN / FAIL means"):
            st.write("**PASS** = Logic worked as expected.")
            st.write("**WARN** = App did not crash, but result should be reviewed manually.")
            st.write("**FAIL** = Something is broken and should be fixed before relying on the app.")


st.caption("Prototype only. Always verify safety, access rights, sea conditions and official fishing regulations.")
