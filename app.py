import math
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import folium
import pandas as pd
import requests
import streamlit.components.v1 as components
import streamlit as st
from geopy.distance import geodesic
from streamlit_folium import st_folium

try:
    from streamlit_geolocation import streamlit_geolocation
except Exception:
    streamlit_geolocation = None

# =====================================================
# CastIQ Pro vNext
# Dynamic SA location search, coastline snapping, ranked spots,
# bait-to-species correction, automatic tide UX, expanded SA species/regulations.
# =====================================================

st.set_page_config(page_title="CastIQ Pro", page_icon="🎣", layout="wide")
st.title("🎣 CastIQ Pro")
st.caption("AI Fishing Intelligence: WHERE to stand. WHERE to cast. WHAT bait to use.")

FEEDBACK_FILE = "feedback_log.csv"
API_CACHE_TTL_SECONDS = 1800
APP_USER_AGENT = "CastIQ-Pro/1.0 (South Africa fishing planner; personal prototype)"

# ---------- Safe secrets: prevents StreamlitSecretNotFoundError ----------
def safe_secret(name: str, default: str = "") -> str:
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)

WORLD_TIDES_API_KEY = safe_secret("WORLD_TIDES_API_KEY", "")
STORMGLASS_API_KEY = safe_secret("STORMGLASS_API_KEY", "")

# ---------- Hardened API layer ----------
API_ENDPOINTS = {
    "open_meteo_weather": "https://api.open-meteo.com/v1/forecast",
    "open_meteo_marine": "https://marine-api.open-meteo.com/v1/marine",
    "nominatim": "https://nominatim.openstreetmap.org/search",
    "overpass": "https://overpass-api.de/api/interpreter",
    "worldtides": "https://www.worldtides.info/api/v3",
    "stormglass_tide": "https://api.stormglass.io/v2/tide/extremes/point",
}
DEFAULT_HEADERS = {"User-Agent": APP_USER_AGENT, "Accept": "application/json"}

def api_key_status() -> Dict[str, str]:
    return {
        "Open-Meteo": "Ready - no key required",
        "Nominatim": "Ready - no key required",
        "Overpass / OSM": "Ready - no key required",
        "WorldTides": "Configured" if bool(WORLD_TIDES_API_KEY) else "Not configured - fallback active",
        "Stormglass": "Configured" if bool(STORMGLASS_API_KEY) else "Not configured - fallback active",
    }

def safe_api_json(method: str, url: str, *, params: Optional[Dict] = None, data: Optional[Dict] = None,
                  headers: Optional[Dict] = None, timeout: int = 12, retries: int = 1,
                  label: str = "API") -> Tuple[Optional[Dict], Optional[str]]:
    request_headers = DEFAULT_HEADERS.copy()
    if headers:
        request_headers.update(headers)
    last_error = None
    for attempt in range(retries + 1):
        try:
            if method.upper() == "POST":
                response = requests.post(url, params=params, data=data, headers=request_headers, timeout=timeout)
            else:
                response = requests.get(url, params=params, headers=request_headers, timeout=timeout)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json(), None
        except Exception as e:
            last_error = f"{label} issue: {e}"
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    return None, last_error

def safe_list_get(values, idx, default=None):
    try:
        if values is None or idx is None or idx >= len(values):
            return default
        return values[idx]
    except Exception:
        return default


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
    "Early Morning": 6,
    "Morning": 9,
    "Midday": 12,
    "Afternoon": 15,
    "Evening": 18,
    "Night": 21,
    "Midnight": 2,
}

ALL_BAITS = [
    "Sardine", "Chokka", "Mackerel", "Red bait", "Prawn", "Mussel", "Cracker shrimp", "Worm",
    "Live mullet", "Fish head", "Octopus", "Bonito", "Spoon lure", "Paddle tail lure", "Small crab",
    "Crayfish", "Fish fillet", "White mussel", "Bloodworm", "Sand prawn", "Pilchard", "Squid",
]

AREA_LOCATIONS = {
    "Umhlanga": (-29.7245, 31.0856),
    "Durban": (-29.8587, 31.0218),
    "Ballito": (-29.5380, 31.2144),
    "Scottburgh": (-30.2867, 30.7532),
    "Port Edward": (-31.0507, 30.2279),
    "Leisure Bay": (-30.9933, 30.2655),
    "Trafalgar": (-30.9579, 30.3008),
    "Palm Beach": (-30.9898, 30.2768),
    "Southbroom": (-30.9192, 30.3287),
    "Cape Town": (-33.9249, 18.4241),
    "Mossel Bay": (-34.1831, 22.1460),
    "Gqeberha / Port Elizabeth": (-33.9608, 25.6022),
    "East London": (-33.0292, 27.8546),
}

# Seeded micro-spots. Dynamic search will also create OSM spots around any SA location.
FISHING_SPOTS = {
    "Umhlanga Lighthouse Gully": {"area": "Umhlanga", "stand": (-29.7256, 31.0886), "feature_type": "gully", "structure": "Rocky gully and white-water edge near lighthouse", "confidence": 80, "species": ["Kob", "Shad", "Garrick", "Blacktail", "Bronze Bream", "Kingfish"], "notes": "Fish the gully edge; use caution on rocks."},
    "Umhlanga Lagoon Mouth Current Seam": {"area": "Umhlanga", "stand": (-29.7155, 31.0934), "feature_type": "river mouth", "structure": "Lagoon-mouth current seam meeting surf line", "confidence": 82, "species": ["Garrick", "Kob", "Spotted Grunter", "Shad", "Pompano"], "notes": "Best around moving tide and clean working water."},
    "Bronze Beach White-Water Section": {"area": "Umhlanga", "stand": (-29.7119, 31.0956), "feature_type": "white water", "structure": "Sandbank drop-off with working white water", "confidence": 76, "species": ["Shad", "Kob", "Garrick", "Pompano", "Grey Shark"], "notes": "Good for Shad when water is active."},
    "Ballito Salmon Bay": {"area": "Ballito", "stand": (-29.5350, 31.2196), "feature_type": "beach", "structure": "Beach and rock-sand transition", "confidence": 74, "species": ["Shad", "Kob", "Blacktail", "Garrick"], "notes": "Look for deeper water and working foam lines."},
    "Salt Rock Main Beach": {"area": "Salt Rock", "stand": (-29.5008, 31.2363), "feature_type": "beach", "structure": "Beach break with scattered reef influence", "confidence": 72, "species": ["Shad", "Kob", "Garrick", "Pompano"], "notes": "Fish early morning or evening."},
    "Southbroom River-Mouth Channel": {"area": "Southbroom", "stand": (-30.9192, 30.3287), "feature_type": "river mouth", "structure": "River-mouth influence with deeper channel", "confidence": 76, "species": ["Kob", "Garrick", "Spotted Grunter", "Pompano", "Shad"], "notes": "Fish the channel seam on moving tide."},
    "Trafalgar Rock-Sand Transition": {"area": "Trafalgar", "stand": (-30.9579, 30.3008), "feature_type": "gully", "structure": "Rock and sand transition with feeding gully", "confidence": 82, "species": ["Kob", "Shad", "Bronze Bream", "Blacktail", "Grey Shark"], "notes": "Target the edge, not the middle."},
    "Palm Beach White-Water Channel": {"area": "Palm Beach", "stand": (-30.9898, 30.2768), "feature_type": "white water", "structure": "Working white water with channel edge", "confidence": 74, "species": ["Shad", "Kob", "Garrick", "Bronze Bream", "Blacktail", "Pompano"], "notes": "Good if water is working."},
    "Port Edward Rocky Point": {"area": "Port Edward", "stand": (-31.0507, 30.2279), "feature_type": "rock", "structure": "Rocky point and gully water", "confidence": 78, "species": ["Kob", "Shad", "Bronze Bream", "Blacktail", "Musselcracker"], "notes": "Safety first; avoid big swell."},
    "Muizenberg / False Bay Strand": {"area": "Cape Town", "stand": (-34.1075, 18.4695), "feature_type": "beach", "structure": "Long surf beach with sand channels", "confidence": 72, "species": ["Kob", "White Steenbras", "Galjoen", "Spotted Grunter"], "notes": "Look for holes and channels."},
    "Strand Beach": {"area": "Cape Town", "stand": (-34.1141, 18.8244), "feature_type": "beach", "structure": "Surf beach with channels", "confidence": 70, "species": ["Kob", "White Steenbras", "Galjoen"], "notes": "Works best around cleaner water and moving tide."},
}

# ---------- Species intelligence ----------
def sp(ideal, time_bonus, trace, bite, feel, response, mistake, group="General", diagram="Main line | sinker | swivel | leader | hook"):
    return {"ideal_baits": ideal, "time_bonus": time_bonus, "trace": trace, "bite_style": bite, "feel": feel, "response": response, "mistake": mistake, "group": group, "trace_diagram": diagram}

SPECIES: Dict[str, Dict] = {
    "Kob": sp(["Chokka", "Sardine", "Mackerel", "Live mullet", "Fish fillet", "Squid", "Pilchard"], ["Early Morning", "Evening", "Night", "Midnight"], "Sliding sinker trace", "Soft pickup → suction feed → slow run", "Light taps then rod loads", "Wait for rod to load, then lift firmly", "Striking too early", "Edible", "Main line | running sinker | swivel | 0.70mm leader | 5/0-7/0 hooks"),
    "Shad": sp(["Sardine", "Pilchard", "Chokka", "Spoon lure", "Mackerel"], ["Early Morning", "Morning", "Afternoon", "Evening"], "Short steel trace", "Fast repeated hits", "Sharp knocks and fast tapping", "Strike quickly and keep pressure", "Leaving bait too static", "Edible", "Main line | swivel | short steel | 1/0-3/0 hook"),
    "Garrick": sp(["Live mullet", "Paddle tail lure", "Spoon lure", "Mackerel"], ["Morning", "Afternoon", "Evening"], "Live bait trace", "Aggressive grab → fast run", "Sharp pull and line speed", "Let circle hook set under pressure", "Striking too hard too early", "Gamefish", "Main line | swivel | leader | 6/0-8/0 circle hook"),
    "Spotted Grunter": sp(["Cracker shrimp", "Sand prawn", "Prawn", "Worm", "Sardine"], ["Early Morning", "Morning", "Evening"], "Light sliding trace", "Gentle pickup and run", "Small taps then steady pull", "Feed line, then tighten smoothly", "Using tackle too heavy", "Edible"),
    "Bronze Bream": sp(["Prawn", "Red bait", "Mussel", "Crayfish", "White mussel"], ["Morning", "Afternoon"], "Short scratching trace", "Small taps → firm pull", "Pecks then strong pull into rocks", "Lift firmly once committed", "Fishing too far out", "Reef"),
    "Blacktail": sp(["Prawn", "Red bait", "Mussel", "Cracker shrimp", "Worm"], ["Morning", "Afternoon", "Evening"], "Light scratching trace", "Quick pecks and small pulls", "Taps and nibbles", "Strike gently and keep tension", "Oversized hooks", "Reef"),
    "Pompano": sp(["Prawn", "Cracker shrimp", "Worm", "Small crab", "Sand prawn"], ["Morning", "Afternoon", "Evening"], "Light surf trace", "Quick pickup in shallow surf", "Sharp taps then pull", "Lift and wind steadily", "Fishing beyond the feeding zone", "Edible"),
    "White Steenbras": sp(["Worm", "Sand prawn", "Prawn", "White mussel", "Cracker shrimp"], ["Early Morning", "Morning", "Evening"], "Long sandy beach trace", "Slow pickup and heavy pull", "Rod slowly loads", "Let it commit, then lift", "Too much tension too early", "Edible"),
    "Sand Steenbras": sp(["Worm", "Sand prawn", "Prawn", "White mussel"], ["Morning", "Afternoon", "Evening"], "Light sandy trace", "Subtle pickup", "Light taps", "Gentle lift", "Overpowering light fish", "Edible"),
    "Galjoen": sp(["Red bait", "White mussel", "Mussel", "Worm"], ["Morning", "Afternoon"], "Short rocky-water trace", "Hard bite in foamy water", "Heavy knock", "Lift and keep clear of rocks", "Fishing calm clean water only", "Reef"),
    "Musselcracker": sp(["Crab", "Small crab", "Crayfish", "Red bait", "Mussel", "Octopus"], ["Morning", "Afternoon"], "Heavy reef trace", "Powerful pull into structure", "Rod buckles hard", "Lock up and pull away from reef", "Fishing too light", "Reef"),
    "Kingfish": sp(["Live mullet", "Paddle tail lure", "Spoon lure", "Bonito", "Mackerel"], ["Morning", "Afternoon", "Evening"], "Lure/livebait trace", "Fast ambush hit", "Line accelerates", "Keep pressure and let drag work", "Drag too tight", "Gamefish"),
    "Queenfish": sp(["Spoon lure", "Paddle tail lure", "Live mullet", "Sardine"], ["Morning", "Afternoon"], "Light lure trace", "Fast surface hit", "Sudden strike", "Keep lure moving", "Slow retrieve", "Gamefish"),
    "Wave Garrick": sp(["Sardine", "Prawn", "Spoon lure", "Worm"], ["Morning", "Afternoon", "Evening"], "Light surf trace", "Sharp little hits in wash", "Fast taps", "Strike lightly", "Hooks too large", "Edible"),
    "Grey Shark": sp(["Mackerel", "Fish head", "Bonito", "Sardine", "Octopus"], ["Evening", "Night", "Midnight"], "Steel shark trace", "Pickup then strong run", "Line peels off", "Let it run then set pressure", "Weak steel/leader", "Sport"),
    "Sand Shark": sp(["Mackerel", "Sardine", "Fish head", "Squid"], ["Evening", "Night"], "Shark trace", "Slow heavy pickup", "Rod loads slowly", "Apply steady pressure", "Fishing too light", "Sport"),
    "Ragged Tooth Shark": sp(["Mackerel", "Bonito", "Fish head", "Octopus"], ["Evening", "Night"], "Heavy shark trace", "Slow pickup then run", "Heavy sustained pull", "Use correct heavy tackle", "Unsafe handling", "Sport"),
    "Bronze Whaler": sp(["Bonito", "Mackerel", "Fish head", "Octopus"], ["Evening", "Night"], "Heavy slide/swim-bait trace", "Powerful long run", "Fast line loss", "Use heavy tackle and safety plan", "Fishing alone", "Sport"),
    "Hammerhead": sp(["Mackerel", "Bonito", "Fish head"], ["Evening", "Night"], "Heavy shark trace", "Powerful run", "Hard sustained pressure", "Use safe release handling", "Unsafe handling", "Sport"),
    "Rockcod": sp(["Prawn", "Crayfish", "Small crab", "Octopus", "Fish fillet"], ["Morning", "Afternoon", "Evening"], "Strong reef trace", "Grab and dive", "Heavy knock into reef", "Pull immediately", "Allowing fish into reef", "Reef"),
    "Stumpnose": sp(["Prawn", "Worm", "White mussel", "Cracker shrimp"], ["Morning", "Afternoon"], "Light scratching trace", "Pecks then pull", "Light taps", "Lift smoothly", "Oversized bait", "Edible"),
}

REGULATIONS = {
    "Kob": {"bag": "Varies by area/species", "min_size": "Verify local rule", "closed": "Verify", "protected": "No", "mpa": "Check MPA", "feedback": "Kob rules vary; verify before keeping."},
    "Shad": {"bag": "4", "min_size": "30 cm", "closed": "Seasonal closure applies", "protected": "No", "mpa": "Check MPA", "feedback": "Do not keep during closure."},
    "Garrick": {"bag": "2", "min_size": "70 cm", "closed": "Verify", "protected": "No", "mpa": "Check MPA", "feedback": "Popular catch-and-release species."},
    "Spotted Grunter": {"bag": "Verify", "min_size": "Verify", "closed": "Open/verify", "protected": "No", "mpa": "Check MPA", "feedback": "Verify local estuary/shore rules."},
    "Bronze Bream": {"bag": "2", "min_size": "30 cm", "closed": "Open/verify", "protected": "No", "mpa": "Check MPA", "feedback": "Commonly restricted reef fish."},
    "Blacktail": {"bag": "5", "min_size": "20 cm", "closed": "Open", "protected": "No", "mpa": "Check MPA", "feedback": "Verify current rules."},
    "Pompano": {"bag": "Verify", "min_size": "Verify", "closed": "Open/verify", "protected": "No", "mpa": "Check MPA", "feedback": "Verify current rules."},
    "White Steenbras": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "Often sensitive", "mpa": "Check MPA", "feedback": "Strongly verify before keeping."},
    "Sand Steenbras": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "No/verify", "mpa": "Check MPA", "feedback": "Verify current rules."},
    "Galjoen": {"bag": "Verify", "min_size": "Verify", "closed": "Seasonal restrictions may apply", "protected": "No/verify", "mpa": "Check MPA", "feedback": "Verify local seasonal rules."},
    "Musselcracker": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "No/verify", "mpa": "Check MPA", "feedback": "Slow-growing reef fish; verify rules."},
    "Kingfish": {"bag": "Verify", "min_size": "Verify", "closed": "Open/verify", "protected": "No/verify", "mpa": "Check MPA", "feedback": "Often released by sport anglers."},
    "Queenfish": {"bag": "Verify", "min_size": "Verify", "closed": "Open/verify", "protected": "No/verify", "mpa": "Check MPA", "feedback": "Verify current rules."},
    "Wave Garrick": {"bag": "Verify", "min_size": "Verify", "closed": "Open/verify", "protected": "No/verify", "mpa": "Check MPA", "feedback": "Verify current rules."},
    "Grey Shark": {"bag": "Catch/release advised", "min_size": "Verify", "closed": "Verify", "protected": "Verify", "mpa": "Check MPA", "feedback": "Use safe release handling."},
    "Sand Shark": {"bag": "Catch/release advised", "min_size": "Verify", "closed": "Verify", "protected": "Verify", "mpa": "Check MPA", "feedback": "Use safe release handling."},
    "Ragged Tooth Shark": {"bag": "Catch/release advised", "min_size": "Verify", "closed": "Verify", "protected": "Verify", "mpa": "Check MPA", "feedback": "Handle carefully; verify protection status."},
    "Bronze Whaler": {"bag": "Catch/release advised", "min_size": "Verify", "closed": "Verify", "protected": "Verify", "mpa": "Check MPA", "feedback": "Use safe release handling."},
    "Hammerhead": {"bag": "Catch/release advised", "min_size": "Verify", "closed": "Verify", "protected": "Verify", "mpa": "Check MPA", "feedback": "Verify current protected species rules."},
    "Rockcod": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "Some species protected", "mpa": "Check MPA", "feedback": "Species-level ID matters."},
    "Stumpnose": {"bag": "Verify", "min_size": "Verify", "closed": "Verify", "protected": "No/verify", "mpa": "Check MPA", "feedback": "Verify local rules."},
}
REG_TABLE = pd.DataFrame([{ "Fish": k, **v } for k, v in REGULATIONS.items()])

# ---------- Geography / coastline engine ----------
def destination_point(start: Tuple[float, float], bearing_deg: float, distance_m: float) -> Tuple[float, float]:
    lat1 = math.radians(start[0]); lon1 = math.radians(start[1]); brng = math.radians(bearing_deg); d = distance_m / 6371000
    lat2 = math.asin(math.sin(lat1)*math.cos(d) + math.cos(lat1)*math.sin(d)*math.cos(brng))
    lon2 = lon1 + math.atan2(math.sin(brng)*math.sin(d)*math.cos(lat1), math.cos(d)-math.sin(lat1)*math.sin(lat2))
    return (math.degrees(lat2), math.degrees(lon2))

def calculate_bearing(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1]-a[1])
    y = math.sin(dlon)*math.cos(lat2)
    x = math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def bearing_to_compass(b: float) -> str:
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[int((b + 11.25) / 22.5) % 16]

def direction_text(deg):
    if deg is None: return "unknown"
    return f"{int(deg)}° {bearing_to_compass(float(deg))}"

def point_to_segment_distance_m(p, a, b):
    # Approximate projection in local metres.
    lat0 = math.radians(p[0])
    def xy(q):
        return ((q[1] - p[1]) * 111320 * math.cos(lat0), (q[0] - p[0]) * 110540)
    px, py = 0, 0; ax, ay = xy(a); bx, by = xy(b)
    dx, dy = bx-ax, by-ay
    if dx == 0 and dy == 0:
        return geodesic(p, a).meters, a
    t = max(0, min(1, ((px-ax)*dx + (py-ay)*dy)/(dx*dx + dy*dy)))
    cx, cy = ax + t*dx, ay + t*dy
    lat = p[0] + cy/110540
    lon = p[1] + cx/(111320*math.cos(lat0))
    return math.hypot(cx, cy), (lat, lon)

@st.cache_data(ttl=86400, show_spinner=False)
def geocode_sa_location(query: str) -> Optional[Dict]:
    if not query.strip():
        return None
    data, err = safe_api_json("GET", API_ENDPOINTS["nominatim"], params={
        "q": f"{query}, South Africa", "format": "json", "limit": 5,
        "countrycodes": "za", "addressdetails": 1}, timeout=12, retries=1, label="Location search")
    if err or not data:
        return None
    best = data[0]
    return {"lat": float(best["lat"]), "lon": float(best["lon"]), "display_name": best.get("display_name", query)}

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_osm_beach_spots(lat: float, lon: float, radius_m: int) -> List[Dict]:
    query = f"""
    [out:json][timeout:20];
    (
      node(around:{radius_m},{lat},{lon})["natural"="beach"];
      way(around:{radius_m},{lat},{lon})["natural"="beach"];
      node(around:{radius_m},{lat},{lon})["leisure"="beach_resort"];
      way(around:{radius_m},{lat},{lon})["leisure"="beach_resort"];
      node(around:{radius_m},{lat},{lon})["waterway"="riverbank"];
      node(around:{radius_m},{lat},{lon})["natural"="bay"];
    );
    out center tags 30;
    """
    data, err = safe_api_json("POST", API_ENDPOINTS["overpass"], data={"data": query}, timeout=25, retries=1, label="OSM beach search")
    if err or not data:
        return []
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        plat, plon = el.get("lat"), el.get("lon")
        if plat is None and "center" in el:
            plat, plon = el["center"].get("lat"), el["center"].get("lon")
        if plat is None:
            continue
        name = tags.get("name") or tags.get("name:en") or tags.get("natural") or "OSM coastal feature"
        out.append({"name": name, "lat": float(plat), "lon": float(plon), "tags": tags})
    seen, clean = set(), []
    for o in out:
        key = (o["name"].lower(), round(o["lat"], 3), round(o["lon"], 3))
        if key not in seen:
            seen.add(key); clean.append(o)
    return clean[:25]

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_coastline_nodes(lat: float, lon: float, radius_m: int = 12000) -> List[Tuple[float, float]]:
    query = f"""
    [out:json][timeout:25];
    way(around:{radius_m},{lat},{lon})["natural"="coastline"];
    (._;>;);
    out body;
    """
    data, err = safe_api_json("POST", API_ENDPOINTS["overpass"], data={"data": query}, timeout=30, retries=1, label="OSM coastline")
    if err or not data:
        return []
    nodes = []
    for el in data.get("elements", []):
        if el.get("type") == "node" and "lat" in el and "lon" in el:
            nodes.append((float(el["lat"]), float(el["lon"])))
    return nodes

def estimate_sea_bearing(coast_point: Tuple[float, float]) -> float:
    # SA ocean is generally east/south-east on KZN/EC and south-west/south on Western Cape.
    lat, lon = coast_point
    if lon > 29: return 115
    if lon > 24: return 150
    if lon > 19: return 180
    return 240

def coastline_snap_engine(origin: Tuple[float, float], inland_m: int = 55, cast_m: int = 85) -> Dict:
    nodes = fetch_coastline_nodes(origin[0], origin[1], 15000)
    if len(nodes) >= 2:
        best_dist, best_point = float("inf"), None
        for i in range(len(nodes)-1):
            d, p = point_to_segment_distance_m(origin, nodes[i], nodes[i+1])
            if d < best_dist:
                best_dist, best_point = d, p
        coast = best_point or min(nodes, key=lambda n: geodesic(origin, n).meters)
        sea_bearing = estimate_sea_bearing(coast)
        stand = destination_point(coast, (sea_bearing + 180) % 360, inland_m)
        cast = destination_point(coast, sea_bearing, cast_m)
        return {"stand": stand, "cast": cast, "coast": coast, "sea_bearing": sea_bearing, "source": "OSM coastline", "distance_to_coast_m": int(best_dist)}
    # fallback: move to nearest seeded coastal spot if inland/unknown
    nearest = min(FISHING_SPOTS.values(), key=lambda s: geodesic(origin, s["stand"]).km)
    coast = nearest["stand"]
    sea_bearing = estimate_sea_bearing(coast)
    stand = destination_point(coast, (sea_bearing + 180) % 360, inland_m)
    cast = destination_point(coast, sea_bearing, cast_m)
    return {"stand": stand, "cast": cast, "coast": coast, "sea_bearing": sea_bearing, "source": "Seeded coastline fallback", "distance_to_coast_m": int(geodesic(origin, coast).meters)}


def build_navigation_plan(user_point: Tuple[float, float], stand_point: Tuple[float, float], cast_point: Tuple[float, float], sea_bearing: float, spot_name: str, spot: Dict) -> Dict:
    """Two-stage navigation: drive to parking/access, then walk to stand."""
    parking = spot.get("parking")
    if not parking:
        parking = destination_point(stand_point, (sea_bearing + 180) % 360, 420)
    parking_note = spot.get("parking_note", "Estimated public access/parking point. Confirm signage, safety and legal parking before leaving your vehicle.")
    walk_distance_m = int(geodesic(parking, stand_point).meters)
    face_bearing = int(calculate_bearing(stand_point, cast_point))
    face_compass = bearing_to_compass(face_bearing)
    instructions = spot.get("walk_instructions") or [
        f"Drive to the parking or beach access point for {spot_name}.",
        "Park only where it is legal and visible. Do not leave valuables in the vehicle.",
        f"From parking, walk roughly {walk_distance_m} metres towards the beach access and shoreline.",
        "Stop at the marked stand point on dry, safe ground above the wash line.",
        f"Face {face_bearing} degrees {face_compass}.",
        f"Cast approximately {int(geodesic(stand_point, cast_point).meters)} metres towards the target marker.",
        "Watch at least three wave sets before stepping near rocks, gullies or river-mouth water.",
    ]
    return {"parking": parking, "parking_note": parking_note, "walk_distance_m": walk_distance_m, "face_bearing": face_bearing, "face_compass": face_compass, "instructions": instructions}

def google_nav_url(origin: Tuple[float, float], dest: Tuple[float, float], mode: str = "driving") -> str:
    return f"https://www.google.com/maps/dir/?api=1&origin={origin[0]},{origin[1]}&destination={dest[0]},{dest[1]}&travelmode={mode}"

def waze_nav_url(dest: Tuple[float, float]) -> str:
    return f"https://waze.com/ul?ll={dest[0]},{dest[1]}&navigate=yes"
# ---------- API/weather/tide ----------
@st.cache_data(ttl=API_CACHE_TTL_SECONDS)
def fetch_conditions(lat, lon, trip_date_str, bucket):
    target_hour = TIME_BUCKET_HOUR.get(bucket, 12)
    result = {"available": False, "weather_error": None, "marine_error": None, "weather_source": "Open-Meteo", "marine_source": "Open-Meteo Marine"}
    weather, err = safe_api_json("GET", API_ENDPOINTS["open_meteo_weather"], params={
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m,wind_direction_10m,pressure_msl,cloud_cover,wind_gusts_10m,visibility",
        "timezone": "auto", "forecast_days": 10}, timeout=12, retries=1, label="Open-Meteo weather")
    if err:
        result["weather_error"] = err
    if weather:
        times = weather.get("hourly", {}).get("time", [])
        idx = next((i for i, t in enumerate(times) if t.startswith(trip_date_str) and int(t[11:13]) == target_hour), 0 if times else None)
        if idx is not None:
            h = weather.get("hourly", {})
            result.update({"available": True, "temperature": safe_list_get(h.get("temperature_2m"), idx), "rain_probability": safe_list_get(h.get("precipitation_probability"), idx), "weather_code": safe_list_get(h.get("weather_code"), idx), "wind_speed": safe_list_get(h.get("wind_speed_10m"), idx), "wind_direction": safe_list_get(h.get("wind_direction_10m"), idx), "pressure": safe_list_get(h.get("pressure_msl"), idx), "cloud_cover": safe_list_get(h.get("cloud_cover"), idx), "wind_gusts": safe_list_get(h.get("wind_gusts_10m"), idx), "visibility": safe_list_get(h.get("visibility"), idx)})
    marine, err = safe_api_json("GET", API_ENDPOINTS["open_meteo_marine"], params={
        "latitude": lat, "longitude": lon,
        "hourly": "wave_height,wave_period,wave_direction,sea_surface_temperature,swell_wave_height,swell_wave_period,swell_wave_direction",
        "timezone": "auto", "forecast_days": 10}, timeout=12, retries=1, label="Open-Meteo marine")
    if err:
        result["marine_error"] = err
    if marine:
        times = marine.get("hourly", {}).get("time", [])
        idx = next((i for i, t in enumerate(times) if t.startswith(trip_date_str) and int(t[11:13]) == target_hour), 0 if times else None)
        if idx is not None:
            h = marine.get("hourly", {})
            result.update({"wave_height": safe_list_get(h.get("wave_height"), idx), "wave_period": safe_list_get(h.get("wave_period"), idx), "wave_direction": safe_list_get(h.get("wave_direction"), idx), "sea_temp": safe_list_get(h.get("sea_surface_temperature"), idx), "swell_height": safe_list_get(h.get("swell_wave_height"), idx), "swell_period": safe_list_get(h.get("swell_wave_period"), idx), "swell_direction": safe_list_get(h.get("swell_wave_direction"), idx)})
    return result

def _normalise_tide_time(raw_time):
    try:
        if isinstance(raw_time, (int, float)):
            return datetime.fromtimestamp(raw_time)
        if isinstance(raw_time, str):
            return datetime.fromisoformat(raw_time.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None
    return None

def infer_tide_stage(extremes, target_dt=None):
    if not extremes or len(extremes) < 2:
        return None
    clean = []
    for e in extremes:
        t = _normalise_tide_time(e.get("dt") or e.get("time") or e.get("date"))
        typ = str(e.get("type", "")).lower()
        if t and typ:
            clean.append({"time": t, "type": typ, **e})
    clean.sort(key=lambda x: x["time"])
    if len(clean) >= 2:
        target_dt = target_dt or datetime.now()
        before = [e for e in clean if e["time"] <= target_dt]
        after = [e for e in clean if e["time"] > target_dt]
        first = (before[-1] if before else clean[0])["type"]
        second = (after[0] if after else clean[-1])["type"]
    else:
        first = str(extremes[0].get("type", "")).lower()
        second = str(extremes[1].get("type", "")).lower()
    if "low" in first and "high" in second:
        return "Pushing tide"
    if "high" in first and "low" in second:
        return "Outgoing tide"
    if "high" in first or "low" in first:
        return "Turning tide"
    return None

@st.cache_data(ttl=API_CACHE_TTL_SECONDS)
def fetch_worldtides(lat, lon, trip_date_str, key):
    if not key:
        return {"available": False, "source": "WorldTides", "status": "No WORLD_TIDES_API_KEY configured", "next_tides": [], "stage": None}
    data, err = safe_api_json("GET", API_ENDPOINTS["worldtides"], params={"extremes": "", "heights": "", "lat": lat, "lon": lon, "date": trip_date_str, "days": 1, "key": key}, timeout=12, retries=1, label="WorldTides")
    if err or not data:
        return {"available": False, "source": "WorldTides", "status": err or "WorldTides returned no data", "next_tides": [], "stage": None}
    if data.get("error"):
        return {"available": False, "source": "WorldTides", "status": f"WorldTides error: {data.get('error')}", "next_tides": [], "stage": None}
    ex = data.get("extremes", [])
    return {"available": bool(ex), "source": "WorldTides", "status": "Live tide loaded" if ex else "WorldTides returned no tide extremes", "next_tides": ex[:6], "stage": infer_tide_stage(ex)}

@st.cache_data(ttl=API_CACHE_TTL_SECONDS)
def fetch_stormglass(lat, lon, trip_date_str, key):
    if not key:
        return {"available": False, "source": "Stormglass", "status": "No STORMGLASS_API_KEY configured", "next_tides": [], "stage": None}
    start = datetime.fromisoformat(trip_date_str); end = start + timedelta(days=1)
    data, err = safe_api_json("GET", API_ENDPOINTS["stormglass_tide"], params={"lat": lat, "lng": lon, "start": start.isoformat(), "end": end.isoformat()}, headers={"Authorization": key}, timeout=12, retries=1, label="Stormglass")
    if err or not data:
        return {"available": False, "source": "Stormglass", "status": err or "Stormglass returned no data", "next_tides": [], "stage": None}
    ex = data.get("data", [])
    return {"available": bool(ex), "source": "Stormglass", "status": "Live tide loaded" if ex else "Stormglass returned no tide extremes", "next_tides": ex[:6], "stage": infer_tide_stage(ex)}

def moon_phase_name(d):
    known_new = datetime(2000, 1, 6).date(); days = (d - known_new).days; phase = (days % 29.53058867) / 29.53058867
    if phase < 0.03 or phase > 0.97: return "New Moon"
    if 0.47 < phase < 0.53: return "Full Moon"
    if phase < 0.25: return "Waxing Crescent"
    if phase < 0.47: return "Waxing Gibbous"
    if phase < 0.75: return "Waning Gibbous"
    return "Waning Crescent"

def estimate_tide_stage(trip_date, bucket):
    h = TIME_BUCKET_HOUR.get(bucket, 12); phase = moon_phase_name(trip_date)
    if phase in ["New Moon", "Full Moon"] and h in [6, 18]: return "Estimated moving tide"
    if h in [6, 18, 21]: return "Estimated pushing/outgoing tide"
    return "Estimated tide unknown"

def get_tide_data(lat, lon, trip_date, bucket, manual_override=None):
    if manual_override and manual_override != "Auto":
        return {"available": False, "source": "Manual override", "status": "Advanced manual override used", "next_tides": [], "stage": manual_override}
    wt = fetch_worldtides(lat, lon, trip_date.strftime("%Y-%m-%d"), WORLD_TIDES_API_KEY)
    if wt["available"] and wt.get("stage"): return wt
    sg = fetch_stormglass(lat, lon, trip_date.strftime("%Y-%m-%d"), STORMGLASS_API_KEY)
    if sg["available"] and sg.get("stage"): return sg
    source_notes = []
    if not WORLD_TIDES_API_KEY: source_notes.append("WorldTides key missing")
    elif wt.get("status"): source_notes.append(wt["status"])
    if not STORMGLASS_API_KEY: source_notes.append("Stormglass key missing")
    elif sg.get("status"): source_notes.append(sg["status"])
    return {"available": False, "source": "Estimated fallback", "status": "Live tide unavailable; using estimated tide. " + " | ".join(source_notes), "next_tides": [], "stage": estimate_tide_stage(trip_date, bucket)}

# ---------- Scoring ----------
def bait_match_engine(available_baits, ideal_baits):
    if not available_baits:
        return "No bait selected", [], "No bait selected. Recommendation will use ideal bait logic only."
    matched = [b for b in available_baits if b in ideal_baits]
    if matched:
        return "Good match", matched, f"Good bait match: {', '.join(matched)}."
    return "Poor match", [], f"Your bait ({', '.join(available_baits)}) does not properly match this target."

def confidence_label(score):
    if score >= 80: return "High"
    if score >= 65: return "Good"
    if score >= 50: return "Medium"
    return "Low"

def weather_code_text(code):
    mapping = {0:"Clear",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Fog",48:"Fog",51:"Drizzle",61:"Rain",63:"Rain",65:"Heavy rain",80:"Showers",95:"Thunderstorm"}
    return mapping.get(code, f"Code {code}" if code is not None else "unknown")

def condition_score_engine(conditions, tide_stage, moon_phase, species, bucket):
    score, pos, neg = 50, [], []
    if any(x in tide_stage for x in ["Pushing", "Outgoing", "moving"]): score += 12; pos.append("Moving/estimated moving tide supports feeding.")
    elif "Turning" in tide_stage: score += 5; pos.append("Turning tide can produce a short bite window.")
    else: score -= 4; neg.append("Tide confidence is weak.")
    if moon_phase in ["New Moon", "Full Moon"]: score += 8; pos.append("New/full moon may support stronger tide movement.")
    wind, wave, period, rain = conditions.get("wind_speed"), conditions.get("wave_height"), conditions.get("wave_period"), conditions.get("rain_probability")
    if wind is not None:
        if wind <= 25: score += 8; pos.append("Wind appears fishable.")
        elif wind <= 40: score -= 2; neg.append("Wind may affect casting.")
        else: score -= 10; neg.append("Strong wind may be difficult or unsafe.")
    if wave is not None:
        if 0.7 <= wave <= 1.8: score += 10; pos.append("Swell may create working water.")
        elif wave < 0.7: score -= 3; neg.append("Sea may be too flat.")
        else: score -= 8; neg.append("Swell may be rough; verify safety.")
    if period is not None:
        if 8 <= period <= 14: score += 5; pos.append("Wave period supports structured surf movement.")
        elif period > 16: score -= 4; neg.append("Long-period swell can create powerful sets.")
    if rain is not None and rain >= 70: score -= 5; neg.append("High rain probability may reduce comfort.")
    if species in SPECIES and bucket in SPECIES[species]["time_bonus"]: score += 6; pos.append(f"Time bucket suits {species}.")
    return max(0, min(95, score)), pos, neg

def correct_target_by_bait(preferred_target, likely_species, available_baits):
    if preferred_target == "Auto select":
        candidates = likely_species or list(SPECIES.keys())
    else:
        candidates = [preferred_target]
    if preferred_target != "Auto select" and preferred_target in SPECIES:
        status, matched, _ = bait_match_engine(available_baits, SPECIES[preferred_target]["ideal_baits"])
        if status == "Good match" or not available_baits:
            return preferred_target, None
    scored = []
    for fish in (likely_species or list(SPECIES.keys())):
        if fish not in SPECIES: continue
        status, matched, _ = bait_match_engine(available_baits, SPECIES[fish]["ideal_baits"])
        s = 50 + len(matched)*12 + (8 if status == "Good match" else 0)
        scored.append((fish, s, matched))
    scored.sort(key=lambda x: x[1], reverse=True)
    suggestion = scored[0][0] if scored else (preferred_target if preferred_target != "Auto select" else "Kob")
    if preferred_target != "Auto select" and suggestion != preferred_target and available_baits:
        return suggestion, f"You selected {preferred_target}, but your bait ({', '.join(available_baits)}) is not aligned to it. Suggested target: {suggestion}."
    return suggestion, None

def score_spot(name, spot, origin, time_bucket, available_baits, preferred_target, conditions=None, tide_stage="Estimated tide unknown"):
    d = geodesic(origin, spot["stand"]).km
    base = spot.get("confidence", 65)
    if spot.get("feature_type") in ["gully", "river mouth", "white water", "rock"]: base += 8
    likely = spot.get("species", [])
    target, correction = correct_target_by_bait(preferred_target, likely, available_baits)
    if target in likely: base += 7
    if target in SPECIES and time_bucket in SPECIES[target]["time_bonus"]: base += 7
    status, matched, _ = bait_match_engine(available_baits, SPECIES.get(target, SPECIES["Kob"])["ideal_baits"])
    if status == "Good match": base += 9
    elif status == "Poor match": base -= 8
    if d <= 5: base += 5
    elif d <= 10: base += 3
    elif d <= 20: base += 1
    return max(15, min(95, int(base))), target, correction

def build_candidate_spots(origin, radius_km):
    candidates = []
    for name, spot in FISHING_SPOTS.items():
        d = geodesic(origin, spot["stand"]).km
        if d <= radius_km:
            candidates.append((name, spot.copy(), d, "Seeded spot"))
    osm_spots = fetch_osm_beach_spots(origin[0], origin[1], int(radius_km*1000))
    for o in osm_spots:
        name = f"{o['name']} (OSM coastal option)"
        d = geodesic(origin, (o["lat"], o["lon"])).km
        feature = "river mouth" if "waterway" in o.get("tags", {}) else "beach"
        species = ["Kob", "Shad", "Garrick", "Pompano", "Blacktail", "Spotted Grunter"] if feature == "beach" else ["Kob", "Spotted Grunter", "Garrick", "Shad"]
        candidates.append((name, {"area": o["name"], "stand": (o["lat"], o["lon"]), "feature_type": feature, "structure": "OpenStreetMap coastal feature near selected location", "confidence": 66, "species": species, "notes": "Dynamically found coastal feature. Confirm access and safety locally."}, d, "Dynamic OSM"))
    if not candidates:
        snap = coastline_snap_engine(origin)
        candidates.append(("Nearest coastline generated spot", {"area": "Nearest coastline", "stand": snap["coast"], "feature_type": "coastline", "structure": "Generated nearest coastline point", "confidence": 60, "species": ["Kob", "Shad", "Garrick", "Blacktail", "Pompano"], "notes": "Generated because no named spot was found within the radius."}, geodesic(origin, snap["coast"]).km, "Generated"))
    return candidates

# =====================================================
# Sidebar
# =====================================================
st.sidebar.header("🔌 API Status")
with st.sidebar.expander("API lock status", expanded=False):
    for api_name, api_status in api_key_status().items():
        st.write(f"**{api_name}:** {api_status}")
    st.caption("Keys can be set in .streamlit/secrets.toml or Windows environment variables. App will not crash if keys are missing.")

st.sidebar.header("📍 Location")
loc_method = st.sidebar.radio("Choose location method", ["Search any South African location", "Use current GPS", "Choose example area", "Enter coordinates"])

if "selected_location" not in st.session_state:
    st.session_state.selected_location = AREA_LOCATIONS["Umhlanga"]
    st.session_state.location_basis = "Default: Umhlanga"

if loc_method == "Search any South African location":
    query = st.sidebar.text_input("Search location", value="Umhlanga", placeholder="e.g. Umhlanga, Ballito, Port Edward")
    if st.sidebar.button("🔎 Search location"):
        g = geocode_sa_location(query)
        if g:
            st.session_state.selected_location = (g["lat"], g["lon"])
            st.session_state.location_basis = f"Search: {g['display_name']}"
        else:
            st.sidebar.error("Location not found. Try a nearby town/beach name.")
elif loc_method == "Use current GPS":
    if streamlit_geolocation:
        loc = streamlit_geolocation()
        if loc and loc.get("latitude") is not None:
            st.session_state.selected_location = (loc["latitude"], loc["longitude"])
            st.session_state.location_basis = "Current GPS location"
    else:
        st.sidebar.warning("streamlit-geolocation not installed. Using fallback.")
    if st.sidebar.button("📍 Refresh GPS"):
        st.rerun()
elif loc_method == "Choose example area":
    area = st.sidebar.selectbox("Example area", list(AREA_LOCATIONS.keys()))
    st.session_state.selected_location = AREA_LOCATIONS[area]
    st.session_state.location_basis = f"Example area: {area}"
else:
    lat = st.sidebar.number_input("Latitude", value=st.session_state.selected_location[0], format="%.6f")
    lon = st.sidebar.number_input("Longitude", value=st.session_state.selected_location[1], format="%.6f")
    st.session_state.selected_location = (lat, lon)
    st.session_state.location_basis = f"Entered coordinates: {lat:.6f}, {lon:.6f}"

user_location = st.session_state.selected_location
location_basis = st.session_state.location_basis

st.sidebar.header("🎯 Trip Setup")
trip_date = st.sidebar.date_input("Fishing date", value=datetime.today().date())
time_bucket = st.sidebar.selectbox("Preferred fishing time", options=list(TIME_BUCKET_WINDOWS.keys()), format_func=lambda x: f"{x} ({TIME_BUCKET_WINDOWS[x]})")
max_travel_km = st.sidebar.selectbox("How far are you willing to travel?", [2, 5, 10, 20, 50, 100], index=2)
casting_ability = st.sidebar.selectbox("Casting ability", ["Beginner: 20–40m", "Average: 40–70m", "Strong caster: 70–110m", "Advanced: 110m+"], index=1)
preferred_target = st.sidebar.selectbox("Preferred target species", ["Auto select"] + sorted(SPECIES.keys()))
available_baits = st.sidebar.multiselect("Bait you have available", ALL_BAITS, max_selections=10)

with st.sidebar.expander("⚙️ Advanced settings", expanded=False):
    inland_m = st.slider("Stand safety distance inland from coastline", 20, 150, 55, 5)
    cast_m = st.slider("Cast target distance seaward from coastline", 30, 180, 85, 5)
    manual_tide_override = st.selectbox("Manual tide override", ["Auto", "Pushing tide", "Outgoing tide", "High tide turning", "Low tide turning", "Slack / not sure"])
    st.caption("Manual tide override is hidden here because normal users should not need to guess tides.")

# =====================================================
# Recommendation calculation
# =====================================================
raw_candidates = build_candidate_spots(user_location, max_travel_km)
ranked_rows = []
for name, spot, dist, source in raw_candidates:
    conf, target, correction = score_spot(name, spot, user_location, time_bucket, available_baits, preferred_target)
    ranked_rows.append({"Spot": name, "Area": spot.get("area", ""), "Distance km": round(dist, 2), "Fishing confidence": conf, "Confidence range": confidence_label(conf), "Suggested target": target, "Structure": spot.get("structure", ""), "Source": source, "_spot": spot, "_correction": correction})
ranked_rows.sort(key=lambda r: r["Fishing confidence"], reverse=True)

spot_labels = [f"{r['Spot']} — {r['Fishing confidence']}% ({r['Confidence range']})" for r in ranked_rows]
if "selected_spot_label" not in st.session_state or st.session_state.selected_spot_label not in spot_labels:
    st.session_state.selected_spot_label = spot_labels[0]

# Main tabs
tabs = st.tabs(["🏠 Home", "🎯 Recommendation", "🛰️ Map", "🎣 Bait & Trace", "🌊 Conditions", "🛡️ Safety", "📏 Regulations", "💎 Packages", "📘 Guide", "❓ FAQ"])

# Choice appears in recommendation tab too, but calculation uses session state.
selected_idx = max(0, spot_labels.index(st.session_state.selected_spot_label) if st.session_state.selected_spot_label in spot_labels else 0)
selected_row = ranked_rows[selected_idx]
best_name = selected_row["Spot"]
spot = selected_row["_spot"]
selected_species, bait_correction_msg = selected_row["Suggested target"], selected_row["_correction"]

snap = coastline_snap_engine(spot["stand"], inland_m=inland_m, cast_m=cast_m)
stand, cast = snap["stand"], snap["cast"]
cast_distance = geodesic(stand, cast).meters
bearing = calculate_bearing(stand, cast)
compass = bearing_to_compass(bearing)
conditions = fetch_conditions(stand[0], stand[1], trip_date.strftime("%Y-%m-%d"), time_bucket)
tide_data = get_tide_data(stand[0], stand[1], trip_date, time_bucket, manual_tide_override)
tide_stage = tide_data["stage"] or "Estimated tide unknown"
moon_phase = moon_phase_name(trip_date)
condition_score, cond_pos, cond_neg = condition_score_engine(conditions, tide_stage, moon_phase, selected_species, time_bucket)
species = SPECIES[selected_species]
bait_status, matched_baits, bait_message = bait_match_engine(available_baits, species["ideal_baits"])
confidence = int(selected_row["Fishing confidence"] * 0.65 + condition_score * 0.35)
confidence = max(0, min(95, confidence))

# =====================================================
# Tabs content
# =====================================================
with tabs[0]:
    st.markdown("""
    # 🎣 CastIQ Pro
    ### More fishing. Less guessing.
    Search any South African location, choose your bait, then let the app rank nearby fishing options and snap the fishing setup to the coastline.
    """)
    c1, c2, c3 = st.columns(3)
    c1.info("📍 Dynamic SA location search")
    c2.info("🌊 Coastline snapping: stand on land, cast to sea")
    c3.info("🎣 Bait-realistic species recommendation")

with tabs[1]:
    st.header("🎯 Fishing Recommendation")
    st.write(f"**Location basis:** {location_basis}")
    st.write(f"**Planning GPS:** {user_location[0]:.6f}, {user_location[1]:.6f}")
    st.subheader("Ranked fishing options in your selected radius")
    display_df = pd.DataFrame([{k:v for k,v in r.items() if not k.startswith("_")} for r in ranked_rows])
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    new_label = st.selectbox("Select the fishing option you want to load", spot_labels, index=selected_idx)
    if new_label != st.session_state.selected_spot_label:
        st.session_state.selected_spot_label = new_label
        st.rerun()

    st.divider()
    if bait_correction_msg:
        st.warning(bait_correction_msg)
    elif preferred_target != "Auto select":
        st.success(f"Target/bait check passed for {selected_species}.")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Loaded recommendation", best_name)
        st.write(f"**Area:** {spot.get('area')}")
        st.write(f"**Structure:** {spot.get('structure')}")
        st.write(f"**Why this spot:** {spot.get('notes')}")
        st.info(f"Coastline engine: {snap['source']} | distance from selected point to coast approx. {snap['distance_to_coast_m']}m")
    with col2:
        st.metric("Fishing confidence", f"{confidence}%")
        st.write(f"**Confidence level:** {confidence_label(confidence)}")
        st.write(f"**Selected target:** {selected_species}")
        st.write(f"**Time:** {time_bucket} ({TIME_BUCKET_WINDOWS[time_bucket]})")
        st.write(f"**Tide:** {tide_stage} ({tide_data['source']})")
        st.write(f"**Bait logic:** {bait_message}")
        st.write(f"**Conditions score:** {condition_score}%")
    a,b,c,d = st.columns(4)
    a.metric("Stand GPS", f"{stand[0]:.6f}, {stand[1]:.6f}")
    b.metric("Cast GPS", f"{cast[0]:.6f}, {cast[1]:.6f}")
    c.metric("Cast distance", f"{int(cast_distance)} m")
    d.metric("Direction", f"{int(bearing)}° {compass}")
    st.info(f"Stand at the person marker. Face {int(bearing)}° {compass}. Cast approximately {int(cast_distance)}m.")

with tabs[2]:
    st.header("🛰️ Map + Navigation")
    nav_plan = build_navigation_plan(user_location, stand, cast, snap["sea_bearing"], best_name, spot)
    parking = nav_plan["parking"]
    center = [(stand[0]+cast[0]+parking[0])/3, (stand[1]+cast[1]+parking[1])/3]
    m = folium.Map(location=center, zoom_start=16, tiles=None)
    folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Esri World Imagery", name="Satellite").add_to(m)
    folium.Marker(user_location, popup="Planning/search point", tooltip="Planning/search point", icon=folium.Icon(color="blue", icon="search", prefix="fa")).add_to(m)
    folium.Marker(parking, popup="🅿️ Parking / access point", tooltip="🅿️ Parking / access point", icon=folium.Icon(color="purple", icon="car", prefix="fa")).add_to(m)
    folium.Marker(snap["coast"], popup="Nearest coastline", tooltip="Nearest coastline", icon=folium.Icon(color="green", icon="water", prefix="fa")).add_to(m)
    folium.Marker(stand, popup="🎣 Stand here", tooltip="🎣 Stand here", icon=folium.DivIcon(html='<div style="font-size:34px; line-height:34px; text-align:center;">🧍‍♂️</div>')).add_to(m)
    folium.Marker(cast, popup="🎯 Cast target", tooltip="🎯 Cast target", icon=folium.Icon(color="red", icon="bullseye", prefix="fa")).add_to(m)
    folium.PolyLine([parking, stand], color="orange", weight=5, tooltip=f"Walk-in route approx. {nav_plan['walk_distance_m']}m").add_to(m)
    folium.PolyLine([stand, cast], color="blue", weight=5, tooltip=f"Cast {int(cast_distance)}m at {int(bearing)}° {compass}").add_to(m)
    folium.Circle(cast, radius=18, fill=True, popup="Bait landing zone").add_to(m)
    st_folium(m, width=1150, height=560)

    st.subheader("🚗 Two-stage navigation")
    n1, n2, n3 = st.columns(3)
    with n1:
        st.metric("Drive target", "Parking / access")
        st.caption(nav_plan["parking_note"])
        st.link_button("🚗 Navigate to parking", google_nav_url(user_location, parking, "driving"))
        st.link_button("🚙 Open in Waze", waze_nav_url(parking))
    with n2:
        st.metric("Walk-in", f"±{nav_plan['walk_distance_m']} m")
        st.caption("Use this once parked. Beach paths may not be perfectly mapped, so use the stand marker as the final target.")
        st.link_button("🚶 Walk parking → stand", google_nav_url(parking, stand, "walking"))
    with n3:
        st.metric("Stand + cast", f"Face {nav_plan['face_bearing']}° {nav_plan['face_compass']}")
        st.caption(f"Cast approximately {int(cast_distance)}m to the target marker.")
        st.link_button("📍 Walk my current point → stand", google_nav_url(user_location, stand, "walking"))

    st.subheader("🔊 Voice-style stand instructions")
    instruction_text = " ".join(nav_plan["instructions"])
    for i, step in enumerate(nav_plan["instructions"], 1):
        st.write(f"**{i}.** {step}")
    components.html(f"""
        <button onclick="speechSynthesis.cancel(); var u = new SpeechSynthesisUtterance({instruction_text!r}); u.rate = 0.92; u.pitch = 1; speechSynthesis.speak(u);" style="padding:10px 14px;border-radius:10px;border:1px solid #ddd;cursor:pointer;">🔊 Read directions aloud</button>
        <button onclick="speechSynthesis.cancel();" style="padding:10px 14px;border-radius:10px;border:1px solid #ddd;cursor:pointer;margin-left:8px;">Stop voice</button>
    """, height=55)
    st.warning("Navigation is advisory. Confirm public access, legal parking, surf conditions, tides and personal safety before walking to the stand point.")
with tabs[3]:
    st.header("🎣 Bait & Trace")
    st.write(f"**Selected target used for report:** {selected_species}")
    st.write(f"**Ideal bait:** {', '.join(species['ideal_baits'])}")
    st.write(f"**Your bait:** {', '.join(available_baits) if available_baits else 'Not selected'}")
    if bait_status == "Good match": st.success(bait_message)
    elif bait_status == "Poor match": st.warning(bait_message)
    else: st.info(bait_message)
    st.subheader("Recommended trace")
    st.write(species["trace"])
    st.code(species["trace_diagram"])
    st.subheader("🐟 Bite Behaviour")
    st.write(f"**Bite style:** {species['bite_style']}")
    st.write(f"**Feel:** {species['feel']}")
    st.write(f"**Response:** {species['response']}")
    st.warning(f"Common mistake: {species['mistake']}")

with tabs[4]:
    st.header("🌊 Conditions")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.subheader("Weather")
        if conditions.get("available"):
            st.write(f"Temperature: {conditions.get('temperature')} °C")
            st.write(f"Weather: {weather_code_text(conditions.get('weather_code'))}")
            st.write(f"Rain probability: {conditions.get('rain_probability')}%")
            st.write(f"Pressure: {conditions.get('pressure')} hPa")
            st.write(f"Gusts: {conditions.get('wind_gusts')} km/h")
        else: st.warning("Weather unavailable")
        if conditions.get("weather_error"): st.warning(conditions["weather_error"])
    with c2:
        st.subheader("Wind + Marine")
        st.write(f"Wind: {conditions.get('wind_speed')} km/h from {direction_text(conditions.get('wind_direction'))}")
        st.write(f"Wave height: {conditions.get('wave_height')} m")
        st.write(f"Wave period: {conditions.get('wave_period')} sec")
        st.write(f"Wave direction: {direction_text(conditions.get('wave_direction'))}")
        st.write(f"Swell: {conditions.get('swell_height')} m / {conditions.get('swell_period')} sec")
        st.write(f"Sea temp: {conditions.get('sea_temp')} °C")
        if conditions.get("marine_error"): st.warning(conditions["marine_error"])
    with c3:
        st.subheader("Tide + Moon")
        st.write(f"Tide stage: {tide_stage}")
        st.write(f"Tide source: {tide_data['source']}")
        st.caption(tide_data["status"])
        st.write(f"Moon phase: {moon_phase}")
        st.metric("Conditions score", f"{condition_score}%")
    if tide_data.get("next_tides"):
        st.dataframe(pd.DataFrame(tide_data["next_tides"]), use_container_width=True)
    if cond_pos: st.success("Positive signals: " + " | ".join(cond_pos))
    if cond_neg: st.warning("Caution signals: " + " | ".join(cond_neg))

with tabs[5]:
    st.header("🛡️ Safety")
    st.warning("Safety risk: Medium / verify locally")
    st.write("Check surf sets, rocks, parking, access rights, lighting and security. Avoid isolated night fishing and do not fish dangerous ledges in big swell.")
    if snap["distance_to_coast_m"] > 3000:
        st.info("Your searched/GPS point appears inland. The app snapped the fishing setup to the nearest coastline. Confirm the actual access route before travelling.")

with tabs[6]:
    st.header("📏 Regulations")
    reg = REGULATIONS.get(selected_species)
    if reg:
        r1,r2,r3 = st.columns(3)
        r1.metric("Bag limit", reg["bag"])
        r2.metric("Minimum size", reg["min_size"])
        r3.metric("Protected", reg["protected"])
        st.write(f"Closed season: {reg['closed']}")
        st.write(f"MPA check: {reg['mpa']}")
        st.info(reg["feedback"])
    else:
        st.warning("Regulation not loaded for this species yet.")
    st.dataframe(REG_TABLE, use_container_width=True, hide_index=True)
    st.warning("Prototype regulation guide only. Verify current South African regulations, MPAs, closed seasons and local rules before keeping fish.")

with tabs[7]:
    st.header("💎 Packages")
    for title, desc in [("Free", "Area-level guidance"), ("Pro", "Ranked spots + bait + trace"), ("Elite", "Dynamic coastline + live tide/weather"), ("Guide", "Client planning and trip packs")]:
        st.subheader(title); st.write(desc)

with tabs[8]:
    st.header("📘 User Guide")
    st.markdown("""
    1. Search any South African location or use GPS.
    2. Set radius, time, bait and target species.
    3. Recommendation tab shows all ranked options high-to-low.
    4. Select any option to refresh the full recommendation.
    5. Map shows planning point, coastline point, stand point and cast point.
    6. Bait mismatch automatically suggests a better species and completes the report for that species.
    """)

with tabs[9]:
    st.header("❓ FAQ")
    st.markdown("""
    **Does CastIQ guarantee fish?** No. It improves decision-making.

    **Why no manual tide dropdown?** Normal users should not have to guess tides. Live tide loads automatically; otherwise an estimate is used. Manual override is under Advanced settings only.

    **Why does the app move my point?** If your selected location is inland or inside a city, the coastline engine snaps the fishing setup to the nearest coast.
    """)

st.divider()
st.subheader("💬 Feedback / Accuracy Improvement")
with st.form("feedback_form"):
    result = st.selectbox("Did the recommendation work?", ["Not fished yet", "Yes - caught fish", "Had bites only", "No action", "Wrong spot", "Wrong bait", "Wrong trace", "Wrong species"])
    actual_species = st.text_input("What species did you catch or see?")
    actual_bait = st.text_input("What bait worked or failed?")
    catch_outcome = st.selectbox("Catch outcome", ["No catch", "Released", "Kept legally", "Unsure"])
    comments = st.text_area("Your suggestion / improvement")
    if st.form_submit_button("Submit Feedback"):
        feedback = {"timestamp": datetime.now().isoformat(), "location_basis": location_basis, "user_lat": user_location[0], "user_lon": user_location[1], "trip_date": str(trip_date), "time_bucket": time_bucket, "tide_stage": tide_stage, "tide_source": tide_data["source"], "condition_score": condition_score, "travel_range_km": max_travel_km, "recommended_best_spot": best_name, "target_species": selected_species, "available_baits": ", ".join(available_baits), "bait_status": bait_status, "result": result, "actual_species": actual_species, "actual_bait": actual_bait, "catch_outcome": catch_outcome, "comments": comments, "confidence": confidence, "cast_distance_m": int(cast_distance), "bearing": int(bearing)}
        df = pd.DataFrame([feedback])
        try: df = pd.concat([pd.read_csv(FEEDBACK_FILE), df], ignore_index=True)
        except FileNotFoundError: pass
        df.to_csv(FEEDBACK_FILE, index=False)
        st.success("Feedback saved.")

st.caption("Prototype only. Always verify local regulations, conditions, access rights and safety before fishing.")
