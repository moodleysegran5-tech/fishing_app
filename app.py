import streamlit as st
from streamlit_geolocation import streamlit_geolocation
from geopy.distance import geodesic
import math
import pandas as pd
from datetime import datetime
import folium
from streamlit_folium import st_folium
import os

# =========================
# PAGE SETUP
# =========================

st.set_page_config(
    page_title="CastIQ Pro - Fishing Intelligence",
    page_icon="🎣",
    layout="wide"
)

st.title("🎣 CastIQ Pro")
st.caption("Stand here. Cast there. Use this bait. Fish responsibly.")

FEEDBACK_FILE = "feedback_log.csv"

# =========================
# TIME + BAIT OPTIONS
# =========================

time_bucket_windows = {
    "Early Morning": "04:30 – 07:30",
    "Morning": "07:30 – 10:30",
    "Midday": "10:30 – 14:30",
    "Afternoon": "14:30 – 17:00",
    "Evening": "17:00 – 20:00",
    "Night": "20:00 – 23:59",
    "Midnight": "00:00 – 04:30"
}

all_baits = [
    "Sardine",
    "Chokka",
    "Mackerel",
    "Red bait",
    "Prawn",
    "Mussel",
    "Cracker shrimp",
    "Worm",
    "Live mullet",
    "Fish head",
    "Octopus",
    "Bonito",
    "Spoon lure",
    "Paddle tail lure",
    "Small crab",
    "Crayfish",
    "Fish fillet"
]

# =========================
# HELPER FUNCTIONS
# =========================

def calculate_bearing(start, end):
    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)

    dlon = lon2 - lon1

    x = math.sin(dlon) * math.cos(lat2)
    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )

    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def bearing_to_compass(bearing):
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
    index = round(bearing / 45)
    return directions[index]


def confidence_label(score):
    if score >= 85:
        return "Very High"
    elif score >= 75:
        return "High"
    elif score >= 60:
        return "Medium"
    return "Low"


def bait_match_engine(available_baits, ideal_baits):
    if not available_baits:
        return "No bait selected", [], "No bait selected. The app will recommend ideal bait only."

    matched = []

    for bait in available_baits:
        if bait.lower() in [x.lower() for x in ideal_baits]:
            matched.append(bait)

    if matched:
        return "Good match", matched, f"You have suitable bait: {', '.join(matched)}."

    return "Poor match", [], f"Your bait is not ideal. Best bait: {', '.join(ideal_baits)}."


# =========================
# FISHING SPOTS DATABASE
# =========================

fishing_spots = {
    "Leisure Bay Main Beach": {
        "area": "Leisure Bay, South Coast",
        "stand": (-30.823900, 30.406200),
        "cast": (-30.824250, 30.406650),
        "structure": "Dark sand gully with white-water edge",
        "feature_type": "gully",
        "depth_note": "Estimated deeper gully between shallow sandbanks",
        "confidence": 78,
        "species": ["Kob", "Shad", "Bronze Bream", "Blacktail", "Stone Bream", "Sand Shark", "Grey Shark", "Diamond Ray"],
        "notes": "Good beach structure. Fish the edge where white water meets darker channel."
    },
    "Trafalgar Beach": {
        "area": "Trafalgar, South Coast",
        "stand": (-30.833900, 30.410500),
        "cast": (-30.834300, 30.411050),
        "structure": "Rock and sand transition with feeding gully",
        "feature_type": "gully",
        "depth_note": "Medium-depth gully near rock/sand transition",
        "confidence": 82,
        "species": ["Kob", "Shad", "Bronze Bream", "Blacktail", "Stone Bream", "Grey Shark", "Honeycomb Ray", "Diamond Ray"],
        "notes": "Strong nearby option. Target the gully edge, not the middle."
    },
    "Palm Beach": {
        "area": "Palm Beach, South Coast",
        "stand": (-30.867000, 30.382300),
        "cast": (-30.867420, 30.382850),
        "structure": "Working white water with channel edge",
        "feature_type": "white water",
        "depth_note": "Working white water over sandbank edge",
        "confidence": 74,
        "species": ["Shad", "Kob", "Garrick", "Bronze Bream", "Blacktail", "Pompano", "Grey Shark"],
        "notes": "Good if water is working. Better for shad when there is visible white water."
    },
    "Southbroom Beach": {
        "area": "Southbroom, South Coast",
        "stand": (-30.919200, 30.328700),
        "cast": (-30.919650, 30.329300),
        "structure": "River-mouth influence with deeper channel",
        "feature_type": "river mouth",
        "depth_note": "Channel edge influenced by river-mouth water movement",
        "confidence": 76,
        "species": ["Kob", "Garrick", "Grunter", "Pompano", "Shad", "Sand Shark", "Grey Shark"],
        "notes": "Better around moving tide. Fish the channel and current seam."
    },
    "Umhlanga Rocks": {
        "area": "Durban North",
        "stand": (-29.717820, 31.089420),
        "cast": (-29.718050, 31.089880),
        "structure": "Rock ledge and deep gully",
        "feature_type": "gully",
        "depth_note": "Rocky gully / deeper channel close to ledge",
        "confidence": 77,
        "species": ["Kob", "Garrick", "Shad", "Blacktail", "Bronze Bream", "Kingfish", "Rockcod"],
        "notes": "Classic rock and gully structure. Use caution on rocks."
    }
}

# =========================
# SPECIES ENGINE
# =========================

species_engine = {
    "Kob": {
        "ideal_baits": ["Chokka", "Sardine", "Mackerel", "Live mullet", "Fish fillet"],
        "time_bonus": ["Early Morning", "Evening", "Night", "Midnight"],
        "thinking": "Kob prefer deeper gullies, holes and slower water near the bottom.",
        "bait": "Chokka + sardine combo, mackerel fillet, live bait where legal",
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
        "trace_diagram": "Main Line\n   |\nRunning sinker clip ---- 5oz grapnel\n   |\nSwivel\n   |\nLeader 0.55mm - 0.70mm\n   |\nHook 5/0\n   |\nHook 5/0"
    },
    "Shad": {
        "ideal_baits": ["Sardine", "Chokka", "Spoon lure"],
        "time_bonus": ["Early Morning", "Morning", "Afternoon", "Evening"],
        "thinking": "Shad are aggressive feeders that like white water and moving bait.",
        "bait": "Sardine, chokka strip, spoon lure",
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
        "trace_diagram": "Main Line\n   |\nSwivel\n   |\nShort steel trace\n   |\n1/0 - 3/0 hook\n   |\nSardine / spoon / chokka strip"
    },
    "Garrick": {
        "ideal_baits": ["Live mullet", "Paddle tail lure", "Spoon lure"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Garrick hunt moving bait in current seams, river mouths and channel edges.",
        "bait": "Live mullet, paddle tail lure, spoon lure",
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
        "trace_diagram": "Main Line\n   |\nSwivel\n   |\nLeader / light steel\n   |\nSingle 6/0 - 8/0 circle hook\n   |\nLive mullet"
    },
    "Bronze Bream": {
        "ideal_baits": ["Prawn", "Red bait", "Mussel", "Crayfish"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Bronze bream hold close to rocks, reef edges and foamy water.",
        "bait": "Prawn, red bait, mussel, crayfish where legal",
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
        "trace_diagram": "Main Line\n   |\nSwivel\n   |\nShort leader\n   |\nSmall strong hook\n   |\nPrawn / red bait / mussel"
    },
    "Blacktail": {
        "ideal_baits": ["Prawn", "Sardine", "Mussel", "Red bait"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Blacktail feed close to rocks, gullies and foam pockets.",
        "bait": "Prawn, sardine pieces, mussel, red bait",
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
        "trace_diagram": "Main Line\n   |\nSmall sinker\n   |\nSwivel\n   |\nLight leader\n   |\nSmall hook"
    },
    "Stone Bream": {
        "ideal_baits": ["Prawn", "Mussel", "Red bait"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Stone bream feed around rock pockets and reef edges.",
        "bait": "Prawn, mussel, red bait",
        "trace": "Short scratching trace",
        "leader": "0.40mm to 0.50mm leader",
        "hooks": "1/0 to 2/0 hooks",
        "sinker": "2oz to 4oz sinker",
        "technique": "Place bait close to rocky structure and hold steady.",
        "bite_style": "Small knocks → steady pull",
        "feel": "Taps followed by a firm pull.",
        "response": "Lift firmly and pull away from rocks.",
        "mistake": "Giving too much slack near rocks.",
        "trace_image": "images/stone_bream_trace.png",
        "trace_diagram": "Main Line\n   |\nSwivel\n   |\nShort leader\n   |\n1/0 - 2/0 hook"
    },
    "Grunter": {
        "ideal_baits": ["Prawn", "Cracker shrimp", "Worm"],
        "time_bonus": ["Evening", "Night"],
        "thinking": "Grunter feed over sandbanks, estuary edges and shallow channels.",
        "bait": "Prawn, cracker shrimp, worm",
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
        "trace_diagram": "Main Line\n   |\nSmall running sinker\n   |\nSwivel\n   |\nLight leader\n   |\n1/0 - 2/0 hook"
    },
    "Pompano": {
        "ideal_baits": ["Prawn", "Worm", "Small crab"],
        "time_bonus": ["Morning", "Afternoon"],
        "thinking": "Pompano feed in sandy channels and clean water near banks.",
        "bait": "Prawn, worm, small crab",
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
        "trace_diagram": "Main Line\n   |\nRunning sinker\n   |\nSwivel\n   |\nLight leader\n   |\nPrawn / worm bait"
    },
    "Sand Shark": {
        "ideal_baits": ["Sardine", "Mackerel", "Chokka", "Fish head"],
        "time_bonus": ["Evening", "Night", "Midnight"],
        "thinking": "Sand sharks feed in sandy channels and gullies.",
        "bait": "Sardine, mackerel, chokka, fish head",
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
        "trace_diagram": "Main Line\n   |\nHeavy leader\n   |\nSinker clip\n   |\nLarge hook bait"
    },
    "Grey Shark": {
        "ideal_baits": ["Sardine", "Mackerel", "Bonito", "Chokka"],
        "time_bonus": ["Evening", "Night", "Midnight"],
        "thinking": "Grey sharks patrol gullies, banks and channels.",
        "bait": "Sardine, mackerel, bonito, chokka",
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
        "trace_diagram": "Main Line\n   |\nHeavy leader\n   |\nSteel bite trace\n   |\nLarge hook"
    },
    "Diamond Ray": {
        "ideal_baits": ["Chokka", "Sardine", "Mackerel", "Octopus"],
        "time_bonus": ["Evening", "Night", "Midnight"],
        "thinking": "Diamond rays feed over sand and channel edges.",
        "bait": "Chokka, sardine, mackerel, octopus",
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
        "trace_diagram": "Main Line\n   |\nHeavy sinker clip\n   |\nSwivel\n   |\nHeavy leader\n   |\nLarge hook bait"
    },
    "Honeycomb Ray": {
        "ideal_baits": ["Octopus", "Chokka", "Mackerel", "Sardine"],
        "time_bonus": ["Evening", "Night", "Midnight"],
        "thinking": "Honeycomb rays favour sandy gullies and deeper banks.",
        "bait": "Octopus, chokka, mackerel, sardine",
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
        "trace_diagram": "Main Line\n   |\nHeavy leader\n   |\nLarge hook\n   |\nLarge bait"
    }
}

if not os.path.exists("images"):
    os.makedirs("images")

# =========================
# LOCATION INPUT
# =========================

st.sidebar.header("📍 Location")

location_method = st.sidebar.radio(
    "Choose location method",
    ["Use phone/laptop GPS", "Enter coordinates"]
)

manual_lat = -30.823900
manual_lon = 30.406200

if location_method == "Use phone/laptop GPS":
    location = streamlit_geolocation()

    if location and location.get("latitude") is not None:
        user_location = (location["latitude"], location["longitude"])
        st.sidebar.success(f"GPS found: {user_location[0]:.6f}, {user_location[1]:.6f}")
    else:
        user_location = (manual_lat, manual_lon)
        st.sidebar.warning("GPS not available. Using Leisure Bay sample.")
else:
    manual_lat = st.sidebar.number_input("Latitude", value=-30.823900, format="%.6f")
    manual_lon = st.sidebar.number_input("Longitude", value=30.406200, format="%.6f")
    user_location = (manual_lat, manual_lon)

# =========================
# TRIP SETUP - MAIN SCREEN
# =========================

st.header("🎯 Trip Setup")

trip_date = st.date_input("Fishing date", value=datetime.today())

time_bucket = st.selectbox(
    "Preferred fishing time",
    list(time_bucket_windows.keys())
)

st.success(f"Selected time window: {time_bucket_windows[time_bucket]}")

casting_ability = st.selectbox(
    "Casting ability",
    ["Beginner: 20–40m", "Average: 40–70m", "Strong caster: 70–110m", "Advanced: 110m+"],
    index=1
)

preferred_target = st.selectbox(
    "Preferred target species",
    ["Auto select"] + list(species_engine.keys())
)

available_baits = st.multiselect(
    "Bait you have available - select up to 10",
    all_baits,
    max_selections=10
)

if available_baits:
    st.info(f"Your bait locker: {', '.join(available_baits)}")
else:
    st.warning("No bait selected yet. Select bait so the app can match bait to species.")

# =========================
# FIND CLOSEST SPOT
# =========================

closest_name = None
closest_distance = float("inf")

for name, spot_data in fishing_spots.items():
    dist = geodesic(user_location, spot_data["stand"]).meters
    if dist < closest_distance:
        closest_distance = dist
        closest_name = name

spot = fishing_spots[closest_name]
stand = spot["stand"]
cast = spot["cast"]

cast_distance = geodesic(stand, cast).meters
bearing = calculate_bearing(stand, cast)
compass = bearing_to_compass(bearing)

likely_species = spot["species"]

# =========================
# TARGET SELECTION LOGIC
# =========================

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

# =========================
# CONFIDENCE ENGINE
# =========================

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

confidence = max(0, min(95, confidence))

# =========================
# MAIN OUTPUT
# =========================

st.divider()

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("🎯 Recommended Fishing Spot")
    st.metric("Closest recommended spot", closest_name)
    st.write(f"**Area:** {spot['area']}")
    st.write(f"**Distance from you:** {closest_distance / 1000:.2f} km")
    st.write(f"**Trip date:** {trip_date}")
    st.write(f"**Trip time:** {time_bucket} ({time_bucket_windows[time_bucket]})")
    st.write(f"**Structure:** {spot['structure']}")
    st.write(f"**Depth note:** {spot['depth_note']}")
    st.write(f"**Notes:** {spot['notes']}")

with col2:
    st.subheader("📊 Recommendation Score")
    st.metric("Fishing confidence", f"{confidence}%")
    st.write(f"**Level:** {confidence_label(confidence)}")
    st.write(f"**Time logic:** {time_reason}")
    st.write(f"**Bait logic:** {bait_message}")

# =========================
# BAIT DECISION
# =========================

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

    if alternative_targets:
        st.info(f"Better target based on your bait at this spot: {', '.join(alternative_targets)}")
    else:
        st.info(f"Recommended to obtain: {', '.join(species['ideal_baits'])}")
else:
    st.info("Select bait above to get bait matching advice.")

# =========================
# STAND AND CAST DISPLAY
# =========================

st.divider()
st.subheader("📍 Stand Here → Cast There")

c1, c2, c3, c4 = st.columns(4)

c1.metric("Stand GPS", f"{stand[0]:.6f}, {stand[1]:.6f}")
c2.metric("Cast GPS", f"{cast[0]:.6f}, {cast[1]:.6f}")
c3.metric("Cast Distance", f"{int(cast_distance)} m")
c4.metric("Direction", f"{int(bearing)}° {compass}")

st.info(
    f"Stand at the GPS point. Face {int(bearing)}° {compass}. "
    f"Cast approximately {int(cast_distance)}m into the target structure."
)

# =========================
# SATELLITE MAP
# =========================

st.subheader("🛰️ Satellite View: Stand Point → Cast Direction")

map_center = [
    (stand[0] + cast[0]) / 2,
    (stand[1] + cast[1]) / 2
]

m = folium.Map(location=map_center, zoom_start=17, tiles=None)

folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery",
    name="Satellite",
    overlay=False,
    control=True
).add_to(m)

folium.Marker(
    location=[user_location[0], user_location[1]],
    popup="Your current location",
    tooltip="You are here",
    icon=folium.Icon(color="blue", icon="user")
).add_to(m)

folium.Marker(
    location=[stand[0], stand[1]],
    popup="Stand here",
    tooltip="Stand here",
    icon=folium.Icon(color="green", icon="flag")
).add_to(m)

folium.Marker(
    location=[cast[0], cast[1]],
    popup=f"Cast target: {int(cast_distance)}m",
    tooltip="Cast target",
    icon=folium.Icon(color="red", icon="screenshot")
).add_to(m)

folium.PolyLine(
    locations=[[stand[0], stand[1]], [cast[0], cast[1]]],
    weight=5,
    opacity=0.9,
    tooltip=f"Cast {int(cast_distance)}m at {int(bearing)}° {compass}"
).add_to(m)

folium.Circle(
    location=[cast[0], cast[1]],
    radius=15,
    popup="Estimated bait landing zone / target gully",
    tooltip="Bait landing zone",
    fill=True
).add_to(m)

st_folium(m, width=1150, height=560)

# =========================
# CASTING CHECK
# =========================

st.subheader("🎯 Casting Ability Check")

if "Beginner" in casting_ability and cast_distance > 40:
    st.warning("This target may be too far for a beginner. Look for closer white water or a near-shore channel.")
elif "Average" in casting_ability and cast_distance > 70:
    st.warning("This cast is at the upper end for an average caster.")
elif "Strong" in casting_ability and cast_distance > 110:
    st.warning("This cast may be beyond strong-caster range.")
else:
    st.success("This casting distance matches your selected ability range.")

# =========================
# SPECIES OUTPUT
# =========================

st.divider()
st.subheader("🐟 Species Prediction")

st.write("Likely species at this spot:")

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

# =========================
# BITE BEHAVIOUR
# =========================

st.subheader("🐟 Bite Behaviour")

st.write(f"**Bite style:** {species['bite_style']}")
st.write(f"**What it feels like:** {species['feel']}")
st.write(f"**What you must do:** {species['response']}")
st.warning(f"Common mistake: {species['mistake']}")

# =========================
# TRACE DIAGRAM + IMAGE
# =========================

st.subheader("🧵 Trace Diagram")
st.code(species["trace_diagram"])

st.subheader("🖼️ Trace End Product Image")

trace_image_path = species.get("trace_image")

if trace_image_path and os.path.exists(trace_image_path):
    st.image(trace_image_path, caption=f"{selected_species} trace setup", use_container_width=True)
else:
    st.info(f"Trace image not loaded yet. Add image here: {trace_image_path}")

# =========================
# RESPONSIBLE FISHING
# =========================

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

# =========================
# ADAPTIVE COACH
# =========================

st.divider()
st.subheader("🔁 If Nothing Happens After 30 Minutes")

if selected_species == "Kob":
    st.write("""
1. Cast 10–15m shorter to fish the near edge of the gully.
2. Move slightly left or right to change your angle.
3. If water is very active, switch to Shad setup.
4. If your bait is not ideal, get Chokka/Sardine or switch target.
""")
elif selected_species == "Shad":
    st.write("""
1. Speed up retrieval.
2. Use smaller bait pieces.
3. Cast into working white water.
4. If using spoon, vary retrieve speed.
""")
elif selected_species == "Garrick":
    st.write("""
1. Keep live bait moving naturally.
2. Fish the current seam, not dead water.
3. Move until you find baitfish activity.
4. If no live bait, try paddle tail or spoon.
""")
else:
    st.write("""
1. Change bait presentation first.
2. Try closer structure.
3. Reduce tackle size if fish are shy.
4. Move if there is no feeding activity.
""")

# =========================
# USER FEEDBACK
# =========================

st.divider()
st.subheader("💬 Feedback / Accuracy Improvement")

with st.form("feedback_form"):
    result = st.selectbox(
        "Did the recommendation work?",
        [
            "Not fished yet",
            "Yes - caught fish",
            "Had bites only",
            "No action",
            "Wrong spot",
            "Wrong bait",
            "Wrong trace",
            "Wrong species"
        ]
    )

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
            "time_window": time_bucket_windows[time_bucket],
            "spot": closest_name,
            "target_species": selected_species,
            "available_baits": ", ".join(available_baits),
            "recommended_bait": species["bait"],
            "bait_status": bait_status,
            "recommended_trace": species["trace"],
            "result": result,
            "actual_species": actual_species,
            "actual_bait": actual_bait,
            "catch_outcome": catch_outcome,
            "comments": comments,
            "confidence": confidence,
            "stand_lat": stand[0],
            "stand_lon": stand[1],
            "cast_lat": cast[0],
            "cast_lon": cast[1],
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

# =========================
# SAFETY
# =========================

st.divider()

st.warning("""
Safety note:
This app provides fishing guidance based on rules and estimated structure.
Always check waves, tide, rocks, marine restrictions, local laws and personal safety before fishing.
Do not fish dangerous rocks or closed areas.
""")