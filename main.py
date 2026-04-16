import re
import html
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from collections import namedtuple
from datetime import datetime, timezone

import openai
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel, field_validator

# ── STARTUP VALIDATION ────────────────────────────────────────────────────────
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")
MARKET_API_URL = os.environ.get("MARKET_API_URL")
MARKET_API_KEY = os.environ.get("MARKET_API_KEY")
KMD_API_URL = os.environ.get("KMD_API_URL", "")
KMD_API_KEY = os.environ.get("KMD_API_KEY", "")
NASA_POWER_API_URL = os.environ.get("NASA_POWER_API_URL", "https://power.larc.nasa.gov/api/temporal/daily/point")
KNBS_MARKET_API_URL = os.environ.get("KNBS_MARKET_API_URL", "")
KNBS_API_KEY = os.environ.get("KNBS_API_KEY", "")
MINISTRY_MARKET_API_URL = os.environ.get("MINISTRY_MARKET_API_URL", "")
MINISTRY_MARKET_API_KEY = os.environ.get("MINISTRY_MARKET_API_KEY", "")
VOICE_PHONE_NUMBER = os.environ.get("VOICE_PHONE_NUMBER", "")

if not OPENAI_API_KEY and not GROQ_API_KEY:
    raise RuntimeError("OPENAI_API_KEY or GROQ_API_KEY must be set. App cannot start.")

if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── IN-MEMORY STORES ──────────────────────────────────────────────────────────
conversation_memory: dict = {}
user_profiles: dict = {}
rate_limit_store: dict = {}   # {ip: [timestamps]}

ALLOWED_COUNTIES = {
    "Nairobi","Kiambu","Nakuru","Kisumu","Siaya","Kakamega","Bungoma",
    "Meru","Embu","Machakos","Kitui","Nyeri","Murang'a","Kirinyaga","Uasin Gishu"
}
ALLOWED_CONTEXTS = {"crops","weather","pests","market","general"}
ALLOWED_LANGUAGES = {"en", "sw", "luo"}
MAX_MESSAGE_LEN  = 1000
RATE_LIMIT       = 20          # requests per minute per IP
API_TIMEOUT      = 30          # seconds

# ── HELPERS ───────────────────────────────────────────────────────────────────
def sanitize(text: str) -> str:
    """Strip newlines/CR and HTML-escape to prevent log/XSS injection."""
    return html.escape(text.replace("\n", " ").replace("\r", " ").strip())

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    window = rate_limit_store.setdefault(ip, [])
    rate_limit_store[ip] = [t for t in window if now - t < 60]
    if len(rate_limit_store[ip]) >= RATE_LIMIT:
        return True
    rate_limit_store[ip].append(now)
    return False

def detect_language(text: str) -> str:
    sw_words = {
        'habari','shamba','mazao','mbolea','mvua','bei','soko','wakulima',
        'kilimo','nafaka','mbegu','ardhi','msimu','panda','vuna','uza',
        'nunua','nini','vipi','wapi','lini','ndiyo','hapana','asante',
        'tafadhali','saidia','nataka','nina','ninataka'
    }
    count = sum(1 for w in sw_words if w in text.lower())
    return 'sw' if count >= 2 else 'en'

def extract_farmer_name(text: str):
    patterns = [
        r'my name is ([A-Za-z]+)', r'i am ([A-Za-z]+)', r"i'm ([A-Za-z]+)",
        r'jina langu ni ([A-Za-z]+)', r'mimi ni ([A-Za-z]+)', r'naitwa ([A-Za-z]+)'
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).capitalize()
    return None

def get_client():
    return Groq(api_key=GROQ_API_KEY)


def fetch_json(url: str, timeout: int = 15, headers: dict | None = None) -> dict | list | None:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.load(resp)


def geocode_location(location: str) -> dict | None:
    if not OPENWEATHER_API_KEY or not location:
        return None
    try:
        query = urllib.parse.urlencode({"q": location, "limit": 1, "appid": OPENWEATHER_API_KEY})
        url = f"https://api.openweathermap.org/geo/1.0/direct?{query}"
        data = fetch_json(url, timeout=15)
        if isinstance(data, list) and data:
            return data[0]
    except Exception as e:
        logger.warning("Geocoding failed for %s: %s", location, sanitize(str(e)))
    return None


def reverse_geocode(lat: float, lon: float) -> dict | None:
    if not OPENWEATHER_API_KEY:
        return None
    try:
        query = urllib.parse.urlencode({
            "lat": lat,
            "lon": lon,
            "limit": 1,
            "appid": OPENWEATHER_API_KEY,
        })
        url = f"https://api.openweathermap.org/geo/1.0/reverse?{query}"
        data = fetch_json(url, timeout=15)
        if isinstance(data, list) and data:
            return data[0]
    except Exception as e:
        logger.warning("Reverse geocoding failed for %.4f, %.4f: %s", lat, lon, sanitize(str(e)))
    return None


def fetch_openweather(lat: float, lon: float, location: str) -> dict | None:
    if not OPENWEATHER_API_KEY:
        return None
    try:
        query = urllib.parse.urlencode({
            "lat": lat,
            "lon": lon,
            "units": "metric",
            "appid": OPENWEATHER_API_KEY,
        })
        url = f"https://api.openweathermap.org/data/2.5/weather?{query}"
        data = fetch_json(url, timeout=15)
        if isinstance(data, dict):
            return {
                "source": "OpenWeather",
                "location": location,
                "temperature_c": data.get("main", {}).get("temp"),
                "feels_like_c": data.get("main", {}).get("feels_like"),
                "humidity": data.get("main", {}).get("humidity"),
                "wind_speed_m_s": data.get("wind", {}).get("speed"),
                "description": data.get("weather", [{}])[0].get("description", ""),
                "pressure": data.get("main", {}).get("pressure"),
                "clouds": data.get("clouds", {}).get("all"),
            }
    except Exception as e:
        logger.warning("OpenWeather fetch failed for %s: %s", location, sanitize(str(e)))
    return None


def fetch_nasa_power(lat: float, lon: float) -> dict | None:
    try:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        query = urllib.parse.urlencode({
            "parameters": "T2M,PRECTOTCORR,RH2M,WS2M",
            "community": "AG",
            "longitude": lon,
            "latitude": lat,
            "start": today,
            "end": today,
            "format": "JSON",
        })
        url = f"{NASA_POWER_API_URL}?{query}"
        data = fetch_json(url, timeout=20)
        if not isinstance(data, dict):
            return None
        params = data.get("properties", {}).get("parameter", {})
        return {
            "source": "NASA POWER",
            "temperature_c": next(iter(params.get("T2M", {}).values()), None),
            "precipitation_mm": next(iter(params.get("PRECTOTCORR", {}).values()), None),
            "humidity": next(iter(params.get("RH2M", {}).values()), None),
            "wind_speed_m_s": next(iter(params.get("WS2M", {}).values()), None),
        }
    except Exception as e:
        logger.warning("NASA POWER fetch failed for %.4f, %.4f: %s", lat, lon, sanitize(str(e)))
    return None


def fetch_kmd_weather(lat: float, lon: float, county: str) -> dict | None:
    if not KMD_API_URL:
        return None
    try:
        query = urllib.parse.urlencode({"lat": lat, "lon": lon, "county": county})
        headers = {"Authorization": f"Bearer {KMD_API_KEY}"} if KMD_API_KEY else {}
        data = fetch_json(f"{KMD_API_URL}?{query}", timeout=20, headers=headers)
        if isinstance(data, dict):
            data["source"] = data.get("source") or "Kenya Meteorological Department"
            return data
    except Exception as e:
        logger.warning("KMD weather fetch failed for %s: %s", county, sanitize(str(e)))
    return None


def fetch_weather(location: str, county: str = "", lat: float | None = None, lon: float | None = None) -> dict | None:
    geo = None
    if lat is None or lon is None:
        geo = geocode_location(location)
        if not geo:
            return None
        lat = geo.get("lat")
        lon = geo.get("lon")
    if lat is None or lon is None:
        return None
    location_label = location or county or "Kenya"
    kmd_data = fetch_kmd_weather(lat, lon, county or location_label)
    openweather_data = fetch_openweather(lat, lon, location_label)
    nasa_data = fetch_nasa_power(lat, lon)
    if not any([kmd_data, openweather_data, nasa_data]):
        return None
    return {
        "location": location_label,
        "latitude": lat,
        "longitude": lon,
        "sources": [v for v in [kmd_data, openweather_data, nasa_data] if v],
        "current": kmd_data or openweather_data or nasa_data,
        "openweather": openweather_data,
        "nasa_power": nasa_data,
        "kmd": kmd_data,
    }


def get_market_data(county: str = "", sublocation: str = "") -> dict:
    params = {"county": county, "sublocation": sublocation}
    external_sources = [
        ("ministry", MINISTRY_MARKET_API_URL, MINISTRY_MARKET_API_KEY),
        ("knbs", KNBS_MARKET_API_URL, KNBS_API_KEY),
        ("market", MARKET_API_URL, MARKET_API_KEY),
    ]
    for source_name, base_url, api_key in external_sources:
        if not base_url:
            continue
        try:
            query_data = {k: v for k, v in params.items() if v}
            if api_key:
                query_data["apikey"] = api_key
            query = urllib.parse.urlencode(query_data)
            url = f"{base_url}?{query}" if query else base_url
            data = fetch_json(url, timeout=15)
            if isinstance(data, dict):
                return {
                    "source": source_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "prices": data,
                }
        except Exception as e:
            logger.warning("%s market fetch failed: %s", source_name, sanitize(str(e)))
    return {
        "source": "internal",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prices": MARKET_PRICES,
    }


def ask_openai(user_message: str, session_id: str, context_data: dict = None, tab_context: str = "general", language: str = "en") -> str:
    try:
        if session_id not in conversation_memory:
            conversation_memory[session_id] = []
            user_profiles[session_id] = {"language": "en", "name": None}

        lang = language
        user_profiles[session_id]["language"] = lang
        name = extract_farmer_name(user_message)
        if name:
            user_profiles[session_id]["name"] = name

        profile = user_profiles[session_id]
        lang_name = {"en": "English", "sw": "Kiswahili", "luo": "Luo"}.get(lang, "English")
        lang_note = f"\nLANGUAGE: {lang_name}. Respond in the same language."
        if profile["name"]:
            lang_note += f"\nFARMER NAME: {profile['name']}. Use their name naturally."

        ctx_note = CONTEXT_INSTRUCTIONS.get(tab_context, "")
        system_content = SYSTEM_PROMPT + lang_note + "\n" + ctx_note

        if context_data:
            system_content += f"\n\nDATA:\n{json.dumps(context_data, indent=2)}"

        messages = [{"role": "system", "content": system_content}]
        messages.extend(conversation_memory[session_id][-10:])
        messages.append({"role": "user", "content": user_message[:MAX_MESSAGE_LEN]})

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=800,
            temperature=0.8,
            timeout=API_TIMEOUT,
        )
        reply = response.choices[0].message.content.strip()
        conversation_memory[session_id].append({"role": "user", "content": user_message[:MAX_MESSAGE_LEN]})
        conversation_memory[session_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        logger.error("OpenAI error: %s", sanitize(str(e)))
        return FALLBACK.get(tab_context, "Sorry, I could not connect. Please try again.")

# ── SOIL DATA ─────────────────────────────────────────────────────────────────
SOIL_DATA = {
    "Nairobi":      {"type":"Clay loam",     "ph":6.5,"fertility":"Medium",    "drainage":"Good"},
    "Kiambu":       {"type":"Red volcanic",  "ph":6.8,"fertility":"High",      "drainage":"Excellent"},
    "Nakuru":       {"type":"Clay",          "ph":7.2,"fertility":"High",      "drainage":"Moderate"},
    "Kisumu":       {"type":"Sandy loam",    "ph":6.0,"fertility":"Medium",    "drainage":"Good"},
    "Siaya":        {"type":"Sandy clay",    "ph":5.8,"fertility":"Low-Medium","drainage":"Poor"},
    "Kakamega":     {"type":"Clay loam",     "ph":6.2,"fertility":"High",      "drainage":"Moderate"},
    "Bungoma":      {"type":"Loam",          "ph":6.5,"fertility":"High",      "drainage":"Good"},
    "Meru":         {"type":"Volcanic loam", "ph":6.9,"fertility":"Very High", "drainage":"Excellent"},
    "Embu":         {"type":"Red volcanic",  "ph":6.7,"fertility":"High",      "drainage":"Good"},
    "Machakos":     {"type":"Sandy loam",    "ph":6.3,"fertility":"Low-Medium","drainage":"Excellent"},
    "Kitui":        {"type":"Sandy",         "ph":6.0,"fertility":"Low",       "drainage":"Excellent"},
    "Nyeri":        {"type":"Volcanic loam", "ph":7.0,"fertility":"Very High", "drainage":"Excellent"},
    "Murang'a":     {"type":"Red volcanic",  "ph":6.8,"fertility":"High",      "drainage":"Good"},
    "Kirinyaga":    {"type":"Clay loam",     "ph":6.5,"fertility":"High",      "drainage":"Moderate"},
    "Uasin Gishu":  {"type":"Clay",          "ph":6.8,"fertility":"High",      "drainage":"Good"},
}

# ── SEASON ────────────────────────────────────────────────────────────────────
def get_current_season():
    month = datetime.now(timezone.utc).month
    if month in [3,4,5]:   return "Long Rains",  "High rainfall — ideal for maize, beans, vegetables"
    if month in [6,7,8]:   return "Cool Dry",    "Moderate temps — good for harvesting and land prep"
    if month in [9,10,11]: return "Short Rains", "Moderate rainfall — suitable for quick-maturing crops"
    return "Hot Dry", "Low rainfall — focus on drought-resistant crops and irrigation"

# ── MARKET PRICES ─────────────────────────────────────────────────────────────
MARKET_PRICES = {
    "Maize":    {"price":3200, "trend":"stable",   "demand":"high"},
    "Beans":    {"price":8500, "trend":"rising",   "demand":"very high"},
    "Sorghum":  {"price":4500, "trend":"stable",   "demand":"medium"},
    "Millet":   {"price":5200, "trend":"rising",   "demand":"medium"},
    "Potatoes": {"price":4000, "trend":"falling",  "demand":"high"},
    "Tomatoes": {"price":3500, "trend":"volatile", "demand":"very high"},
    "Kales":    {"price":2800, "trend":"stable",   "demand":"high"},
    "Cabbage":  {"price":3000, "trend":"stable",   "demand":"high"},
    "Onions":   {"price":6500, "trend":"rising",   "demand":"high"},
    "Carrots":  {"price":4500, "trend":"stable",   "demand":"medium"},
}

# ── CROP DATABASE ─────────────────────────────────────────────────────────────
CROP_DATABASE = {
    "Maize":    {"soil_types":["Clay loam","Loam","Sandy loam","Red volcanic","Volcanic loam"],"ph_range":(5.5,7.5),"seasons":["Long Rains","Short Rains"],"maturity_days":90, "varieties":["H614","DH04","WEMA DT"]},
    "Beans":    {"soil_types":["Loam","Clay loam","Sandy loam","Red volcanic"],               "ph_range":(6.0,7.5),"seasons":["Long Rains","Short Rains"],"maturity_days":75, "varieties":["KK15","Rosecoco","Mwitemania"]},
    "Sorghum":  {"soil_types":["Sandy loam","Sandy","Clay","Sandy clay"],                     "ph_range":(5.5,8.0),"seasons":["Long Rains","Short Rains","Hot Dry"],"maturity_days":120,"varieties":["Seredo","Gadam","KARI Mtama 1"]},
    "Potatoes": {"soil_types":["Volcanic loam","Red volcanic","Loam"],                        "ph_range":(5.0,6.5),"seasons":["Long Rains","Cool Dry"],"maturity_days":90, "varieties":["Shangi","Dutch Robjin","Kenya Mpya"]},
    "Tomatoes": {"soil_types":["Loam","Clay loam","Sandy loam","Red volcanic"],               "ph_range":(6.0,7.0),"seasons":["Long Rains","Short Rains"],"maturity_days":75, "varieties":["Anna F1","Kilele F1","Money Maker"]},
}

def calculate_crop_score(crop_name, crop_data, soil_info, season):
    score = 50
    if soil_info["type"] in crop_data["soil_types"]:          score += 30
    elif any(s in soil_info["type"] for s in crop_data["soil_types"]): score += 15
    ph_min, ph_max = crop_data["ph_range"]
    if ph_min <= soil_info["ph"] <= ph_max:                   score += 20
    elif abs(soil_info["ph"]-ph_min)<0.5 or abs(soil_info["ph"]-ph_max)<0.5: score += 10
    if season in crop_data["seasons"]:                        score += 20
    mkt = MARKET_PRICES.get(crop_name, {})
    score += {"very high":15,"high":10,"medium":5}.get(mkt.get("demand",""),0)
    score += 10 if soil_info["fertility"] in ["High","Very High"] else (5 if soil_info["fertility"]=="Medium" else 0)
    if mkt.get("trend") == "rising":                          score += 5
    return min(score, 100)

CropResult = namedtuple("CropResult", ["recommendations","soil","season","season_desc"])

def get_crop_recommendations(county: str, sublocation: str) -> CropResult:
    soil   = SOIL_DATA.get(county, {"type":"Loam","ph":6.5,"fertility":"Medium","drainage":"Good"})
    season, season_desc = get_current_season()
    recs = []
    for name, data in CROP_DATABASE.items():
        score   = calculate_crop_score(name, data, soil, season)
        mkt     = MARKET_PRICES.get(name, {"price":0,"trend":"stable","demand":"medium"})
        variety = data["varieties"][0]
        recs.append({
            "name":   f"{name} ({variety})",
            "detail": f"Plant now · {data['maturity_days']} days · KES {mkt['price']:,}/bag · {mkt['trend'].capitalize()} price",
            "score":  score,
        })
    recs.sort(key=lambda x: x["score"], reverse=True)
    return CropResult(recs[:3], soil, season, season_desc)

# ── SYSTEM PROMPT ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are "Fahamu Shamba," an AI agricultural assistant for Kenyan farmers.
Provide ONLY agricultural guidance. Politely decline non-agricultural queries.

Rules:
- Respond in the farmer's detected language (English or Kiswahili).
- Be warm, concise, and actionable.
- Personalize using conversation history and farmer name if known.

Sections:
1. crops   — Top 3 crop recommendations with suitability reasoning.
2. weather — Weather, season, rainfall, temperature, and farming timing only.
3. pests   — Pest/disease identification, prevention, and treatment only.
4. market  — Market prices, trends, demand, and selling advice only.
5. general — Any agricultural question: soil, fertilizer, irrigation, storage, etc.

Always stay focused on the active section context provided.
If actual weather or market data is provided in DATA, use it directly to answer the user.
Provide concise, location-specific agricultural guidance based on the available data.
"""

CONTEXT_INSTRUCTIONS = {
    "crops":   "CONTEXT: CROP RECOMMENDATIONS — focus only on what to plant, why, and how.",
    "weather": "CONTEXT: WEATHER — focus only on season, rainfall, temperature, and weather-based farming advice.",
    "pests":   "CONTEXT: PEST & DISEASES — focus only on pest/disease identification, prevention, and treatment.",
    "market":  "CONTEXT: MARKET PRICES — focus only on prices, trends, demand, and best time to sell.",
    "general": "CONTEXT: GENERAL QUESTIONS — answer any agricultural question comprehensively.",
}

# ── FALLBACK RESPONSES ────────────────────────────────────────────────────────
FALLBACK = {
    "crops":   "🌾 Based on Kenya's current season, consider planting Maize, Beans, or Tomatoes. Set your location for personalized advice.",
    "weather": "☀️ Kenya is currently in a seasonal transition. Monitor KMD forecasts and prepare your land accordingly.",
    "pests":   "🐛 Common pests in Kenya include Fall Armyworm, Aphids, and Thrips. Use certified pesticides and practice crop rotation.",
    "market":  "📈 Beans and Onions have rising demand. Maize prices are stable. Sell after peak harvest season for better prices.",
    "general": "🌱 I'm here to help with any farming question. Ask about soil, fertilizers, irrigation, or crop management!",
}

def ask_groq(user_message: str, session_id: str, context_data: dict = None, tab_context: str = "general", language: str = "en") -> str:
    try:
        client = get_client()
        if session_id not in conversation_memory:
            conversation_memory[session_id] = []
            user_profiles[session_id] = {"language": "en", "name": None}

        lang = language
        user_profiles[session_id]["language"] = lang
        name = extract_farmer_name(user_message)
        if name:
            user_profiles[session_id]["name"] = name

        profile = user_profiles[session_id]
        lang_name = {"en": "English", "sw": "Kiswahili", "luo": "Luo"}.get(lang, "English")
        lang_note = f"\nLANGUAGE: {lang_name}. Respond in the same language."
        if profile["name"]:
            lang_note += f"\nFARMER NAME: {profile['name']}. Use their name naturally."

        ctx_note = CONTEXT_INSTRUCTIONS.get(tab_context, "")
        system_content = SYSTEM_PROMPT + lang_note + "\n" + ctx_note

        if context_data:
            system_content += f"\n\nDATA:\n{json.dumps(context_data, indent=2)}"

        messages = [{"role": "system", "content": system_content}]
        messages.extend(conversation_memory[session_id][-10:])
        messages.append({"role": "user", "content": user_message[:MAX_MESSAGE_LEN]})

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=800,
            temperature=0.8,
            timeout=API_TIMEOUT,
        )
        reply = response.choices[0].message.content.strip()
        conversation_memory[session_id].append({"role": "user",      "content": user_message[:MAX_MESSAGE_LEN]})
        conversation_memory[session_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        logger.error("Groq error: %s", sanitize(str(e)))
        return FALLBACK.get(tab_context, "Sorry, I could not connect. Please try again.")


def ask_ai(user_message: str, session_id: str, context_data: dict = None, tab_context: str = "general", language: str = "en") -> str:
    if OPENAI_API_KEY:
        return ask_openai(user_message, session_id, context_data, tab_context, language)
    return ask_groq(user_message, session_id, context_data, tab_context, language)

# ── REQUEST MODEL ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message:     str
    session_id:  str  = "default"
    county:      str  = ""
    sublocation: str  = ""
    context:     str  = "general"
    language:    str  = "en"
    village:     str  = ""
    latitude:    float | None = None
    longitude:   float | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v[:MAX_MESSAGE_LEN]

    @field_validator("session_id")
    @classmethod
    def validate_session(cls, v):
        v = v.strip()
        if not v or len(v) > 100:
            return "default"
        return re.sub(r"[^a-zA-Z0-9_\-]", "", v) or "default"

    @field_validator("county")
    @classmethod
    def validate_county(cls, v):
        return v.strip() if v.strip() in ALLOWED_COUNTIES else ""

    @field_validator("sublocation")
    @classmethod
    def validate_sublocation(cls, v):
        return v.strip()[:100]

    @field_validator("village")
    @classmethod
    def validate_village(cls, v):
        return v.strip()[:100]

    @field_validator("context")
    @classmethod
    def validate_context(cls, v):
        return v if v in ALLOWED_CONTEXTS else "general"

    @field_validator("language")
    @classmethod
    def validate_language(cls, v):
        return v if v in ALLOWED_LANGUAGES else "en"

    @field_validator("latitude", "longitude")
    @classmethod
    def validate_coordinates(cls, v):
        return v if v is None else float(v)

# ── ENDPOINTS ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/app-config")
async def app_config():
    return {
        "voice_number": VOICE_PHONE_NUMBER,
        "voice_call_enabled": bool(VOICE_PHONE_NUMBER),
        "geolocation_enabled": True,
    }

@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    if is_rate_limited(ip):
        return JSONResponse({"reply": "Too many requests. Please wait a moment.", "language": "en"}, status_code=429)

    context_data  = None
    recommendations = None
    msg_lower = req.message.lower()

    weather_data = None
    market_data = get_market_data(req.county, req.sublocation)

    if req.county:
        location_text = f"{req.sublocation}, {req.county}".strip(', ')
        if (req.latitude is not None and req.longitude is not None) and not req.sublocation:
            reverse_geo = reverse_geocode(req.latitude, req.longitude)
            if reverse_geo:
                location_text = f"{reverse_geo.get('name', req.county)}, {req.county}"
        context_data = {
            "location":       location_text,
            "village":        req.village or "Unknown",
            "county":         req.county,
            "sublocation":    req.sublocation,
            "latitude":       req.latitude,
            "longitude":      req.longitude,
            "weather_data":   fetch_weather(location_text, req.county, req.latitude, req.longitude),
            "market_data":    market_data,
        }
        weather_data = context_data["weather_data"]

    if req.context == "crops" or any(k in msg_lower for k in ["best crop","what to plant","recommend","top 3","mazao","panda","kilimo","crop"]):
        if req.county:
            result = get_crop_recommendations(req.county, req.sublocation)
            recommendations = result.recommendations
            context_data.update({
                "soil_type":      result.soil["type"],
                "soil_ph":        result.soil["ph"],
                "soil_fertility": result.soil["fertility"],
                "soil_drainage":  result.soil["drainage"],
                "current_season": result.season,
                "season_desc":    result.season_desc,
                "top_3_crops": [
                    {"rank": i+1, "name": r["name"], "score": r["score"], "details": r["detail"]}
                    for i, r in enumerate(result.recommendations)
                ],
            })

    reply = ask_ai(req.message, req.session_id, context_data, req.context, req.language)
    lang  = req.language

    if recommendations:
        return {"reply": reply, "recommendations": recommendations, "language": lang}
    return {"reply": reply, "language": lang}

@app.post("/ussd", response_class=PlainTextResponse)
async def ussd(
    sessionId:   str = Form(...),
    serviceCode: str = Form(...),
    phoneNumber: str = Form(...),
    text:        str = Form(""),
):
    # Validate sessionId
    if not sessionId or len(sessionId) > 100:
        return "END Invalid session."
    safe_sid = re.sub(r"[^a-zA-Z0-9_\-]", "", sessionId) or "default"

    if text == "":
        return "CON Karibu Fahamu Shamba\nWelcome to Fahamu Shamba\n1. Mazao Bora/Best Crops\n2. Wadudu/Pests\n3. Hali ya Hewa/Weather\n4. Bei za Soko/Market Prices"
    if text == "1": return "CON Enter your county (e.g. Nakuru):"
    if text == "2": return "CON Enter crop name (e.g. maize):"
    if text == "3": return "CON Enter your county:"
    if text == "4": return "CON Enter crop name:"

    parts      = text.split("*")
    menu       = parts[0]
    user_input = parts[-1].strip()[:100] if len(parts) > 1 else ""

    if menu == "1" and user_input:
        county = user_input.title()
        if county in ALLOWED_COUNTIES:
            result = get_crop_recommendations(county, "")
            top    = result.recommendations[0]
            return f"END Top crop: {top['name']}\n{top['detail']}"
        return "END Plant maize, beans or sorghum / Panda mahindi, maharagwe au mtama"

    queries = {
        "2": f"Pest management for {user_input}",
        "3": f"Weather advice for {user_input} Kenya",
        "4": f"Market price for {user_input}",
    }
    query  = queries.get(menu, user_input)
    advice = ask_groq(query[:MAX_MESSAGE_LEN], safe_sid, tab_context="general")
    return f"END {advice[:160]}"

@app.post("/voice/incoming")
async def voice_incoming():
    """Twilio voice call entry point — greet and prompt the farmer."""
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice" language="en-KE">
    Welcome to Fahamu Shamba, your smart farming assistant.
    You can ask me about crops, weather, pests, market prices, or any farming question.
    Please speak your question after the beep.
  </Say>
  <Gather input="speech" action="/voice/respond" method="POST"
          language="en-KE" speechTimeout="auto" timeout="10">
    <Say voice="alice" language="en-KE">Go ahead, I am listening.</Say>
  </Gather>
  <Say voice="alice" language="en-KE">I did not hear anything. Please call again. Goodbye.</Say>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.post("/voice/respond")
async def voice_respond(
    request: Request,
    CallSid: str = Form(""),
    SpeechResult: str = Form(""),
    Confidence: str = Form(""),
):
    """Handle the farmer's spoken question and reply conversationally."""
    if not CallSid or len(CallSid) > 100:
        CallSid = "voice_default"
    session_id = "voice_" + re.sub(r"[^a-zA-Z0-9_\-]", "", CallSid)[:80]

    spoken = SpeechResult.strip()[:MAX_MESSAGE_LEN]
    if not spoken:
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice" language="en-KE">Sorry, I could not hear you clearly. Please try again.</Say>
  <Gather input="speech" action="/voice/respond" method="POST"
          language="en-KE" speechTimeout="auto" timeout="10">
    <Say voice="alice" language="en-KE">Please ask your farming question now.</Say>
  </Gather>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    lang = detect_language(spoken)
    reply = ask_ai(spoken, session_id, tab_context="general", language=lang)

    # Strip markdown symbols that sound bad over voice
    voice_reply = re.sub(r"[*_#`>\.]{1,3}", "", reply).strip()
    voice_reply = voice_reply[:600]  # keep TTS short

    voice_lang = "sw-KE" if lang == "sw" else "en-KE"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice" language="{voice_lang}">{html.escape(voice_reply)}</Say>
  <Gather input="speech" action="/voice/respond" method="POST"
          language="{voice_lang}" speechTimeout="auto" timeout="10">
    <Say voice="alice" language="{voice_lang}">Do you have another question? Go ahead.</Say>
  </Gather>
  <Say voice="alice" language="{voice_lang}">Thank you for using Fahamu Shamba. Goodbye and happy farming!</Say>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()
