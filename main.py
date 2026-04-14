import re
import html
import json
import logging
import os
import time
from collections import namedtuple
from datetime import datetime, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel, field_validator

# ── STARTUP VALIDATION ────────────────────────────────────────────────────────
if not os.environ.get("GROQ_API_KEY"):
    raise RuntimeError("GROQ_API_KEY is not set. App cannot start.")

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
    return Groq(api_key=os.environ["GROQ_API_KEY"])

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

def ask_groq(user_message: str, session_id: str, context_data: dict = None, tab_context: str = "general") -> str:
    try:
        client = get_client()
        if session_id not in conversation_memory:
            conversation_memory[session_id] = []
            user_profiles[session_id] = {"language": "en", "name": None}

        lang = detect_language(user_message)
        user_profiles[session_id]["language"] = lang
        name = extract_farmer_name(user_message)
        if name:
            user_profiles[session_id]["name"] = name

        profile = user_profiles[session_id]
        lang_note = f"\nDETECTED LANGUAGE: {'Kiswahili' if lang=='sw' else 'English'}. Respond in the same language."
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

# ── REQUEST MODEL ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message:     str
    session_id:  str  = "default"
    county:      str  = ""
    sublocation: str  = ""
    context:     str  = "general"

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

    @field_validator("context")
    @classmethod
    def validate_context(cls, v):
        return v if v in ALLOWED_CONTEXTS else "general"

# ── ENDPOINTS ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    if is_rate_limited(ip):
        return JSONResponse({"reply": "Too many requests. Please wait a moment.", "language": "en"}, status_code=429)

    context_data  = None
    recommendations = None
    msg_lower = req.message.lower()

    if req.context == "crops" or any(k in msg_lower for k in ["best crop","what to plant","recommend","top 3","mazao","panda","kilimo","crop"]):
        if req.county:
            result = get_crop_recommendations(req.county, req.sublocation)
            recommendations = result.recommendations
            context_data = {
                "location":        f"{req.sublocation}, {req.county}",
                "soil_type":       result.soil["type"],
                "soil_ph":         result.soil["ph"],
                "soil_fertility":  result.soil["fertility"],
                "soil_drainage":   result.soil["drainage"],
                "current_season":  result.season,
                "season_desc":     result.season_desc,
                "top_3_crops": [
                    {"rank": i+1, "name": r["name"], "score": r["score"], "details": r["detail"]}
                    for i, r in enumerate(result.recommendations)
                ],
            }

    reply = ask_groq(req.message, req.session_id, context_data, req.context)
    lang  = user_profiles.get(req.session_id, {}).get("language", "en")

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

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()
