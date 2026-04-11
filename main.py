from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from groq import Groq
import os
import base64
import logging
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

conversation_memory = {}

def get_client():
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY environment variable is not set")
    return Groq(api_key=key)

# ── KENYA SOIL DATA BY COUNTY ────────────────────────────────────────────────
SOIL_DATA = {
    "Nairobi": {"type": "Clay loam", "ph": 6.5, "fertility": "Medium", "drainage": "Good"},
    "Kiambu": {"type": "Red volcanic", "ph": 6.8, "fertility": "High", "drainage": "Excellent"},
    "Nakuru": {"type": "Clay", "ph": 7.2, "fertility": "High", "drainage": "Moderate"},
    "Kisumu": {"type": "Sandy loam", "ph": 6.0, "fertility": "Medium", "drainage": "Good"},
    "Siaya": {"type": "Sandy clay", "ph": 5.8, "fertility": "Low-Medium", "drainage": "Poor"},
    "Kakamega": {"type": "Clay loam", "ph": 6.2, "fertility": "High", "drainage": "Moderate"},
    "Bungoma": {"type": "Loam", "ph": 6.5, "fertility": "High", "drainage": "Good"},
    "Meru": {"type": "Volcanic loam", "ph": 6.9, "fertility": "Very High", "drainage": "Excellent"},
    "Embu": {"type": "Red volcanic", "ph": 6.7, "fertility": "High", "drainage": "Good"},
    "Machakos": {"type": "Sandy loam", "ph": 6.3, "fertility": "Low-Medium", "drainage": "Excellent"},
    "Kitui": {"type": "Sandy", "ph": 6.0, "fertility": "Low", "drainage": "Excellent"},
    "Nyeri": {"type": "Volcanic loam", "ph": 7.0, "fertility": "Very High", "drainage": "Excellent"},
    "Murang'a": {"type": "Red volcanic", "ph": 6.8, "fertility": "High", "drainage": "Good"},
    "Kirinyaga": {"type": "Clay loam", "ph": 6.5, "fertility": "High", "drainage": "Moderate"},
    "Uasin Gishu": {"type": "Clay", "ph": 6.8, "fertility": "High", "drainage": "Good"}
}

# ── CURRENT SEASON & WEATHER PATTERNS ────────────────────────────────────────
def get_current_season():
    month = datetime.now().month
    if month in [3, 4, 5]:
        return "Long Rains", "High rainfall expected, ideal for maize, beans, and vegetables"
    elif month in [6, 7, 8]:
        return "Cool Dry", "Moderate temperatures, good for harvesting and land preparation"
    elif month in [9, 10, 11]:
        return "Short Rains", "Moderate rainfall, suitable for quick-maturing crops"
    else:
        return "Hot Dry", "Low rainfall, focus on drought-resistant crops and irrigation"

# ── MARKET PRICES (KES per 90kg bag) ─────────────────────────────────────────
MARKET_PRICES = {
    "Maize": {"price": 3200, "trend": "stable", "demand": "high"},
    "Beans": {"price": 8500, "trend": "rising", "demand": "very high"},
    "Sorghum": {"price": 4500, "trend": "stable", "demand": "medium"},
    "Millet": {"price": 5200, "trend": "rising", "demand": "medium"},
    "Potatoes": {"price": 4000, "trend": "falling", "demand": "high"},
    "Tomatoes": {"price": 3500, "trend": "volatile", "demand": "very high"},
    "Kales": {"price": 2800, "trend": "stable", "demand": "high"},
    "Cabbage": {"price": 3000, "trend": "stable", "demand": "high"},
    "Onions": {"price": 6500, "trend": "rising", "demand": "high"},
    "Carrots": {"price": 4500, "trend": "stable", "demand": "medium"}
}

# ── CROP SUITABILITY SCORING ─────────────────────────────────────────────────
CROP_DATABASE = {
    "Maize": {
        "soil_types": ["Clay loam", "Loam", "Sandy loam", "Red volcanic", "Volcanic loam"],
        "ph_range": (5.5, 7.5),
        "rainfall": "medium-high",
        "seasons": ["Long Rains", "Short Rains"],
        "maturity_days": 90,
        "varieties": ["H614", "DH04", "WEMA DT"]
    },
    "Beans": {
        "soil_types": ["Loam", "Clay loam", "Sandy loam", "Red volcanic"],
        "ph_range": (6.0, 7.5),
        "rainfall": "medium",
        "seasons": ["Long Rains", "Short Rains"],
        "maturity_days": 75,
        "varieties": ["KK15", "Rosecoco", "Mwitemania"]
    },
    "Sorghum": {
        "soil_types": ["Sandy loam", "Sandy", "Clay", "Sandy clay"],
        "ph_range": (5.5, 8.0),
        "rainfall": "low-medium",
        "seasons": ["Long Rains", "Short Rains", "Hot Dry"],
        "maturity_days": 120,
        "varieties": ["Seredo", "Gadam", "KARI Mtama 1"]
    },
    "Potatoes": {
        "soil_types": ["Volcanic loam", "Red volcanic", "Loam"],
        "ph_range": (5.0, 6.5),
        "rainfall": "medium-high",
        "seasons": ["Long Rains", "Cool Dry"],
        "maturity_days": 90,
        "varieties": ["Shangi", "Dutch Robjin", "Kenya Mpya"]
    },
    "Tomatoes": {
        "soil_types": ["Loam", "Clay loam", "Sandy loam", "Red volcanic"],
        "ph_range": (6.0, 7.0),
        "rainfall": "medium",
        "seasons": ["Long Rains", "Short Rains"],
        "maturity_days": 75,
        "varieties": ["Anna F1", "Kilele F1", "Money Maker"]
    }
}

def calculate_crop_score(crop_name, crop_data, soil_info, season, season_desc):
    score = 50  # Base score
    
    # Soil type match (30 points)
    if soil_info["type"] in crop_data["soil_types"]:
        score += 30
    elif any(s in soil_info["type"] for s in crop_data["soil_types"]):
        score += 15
    
    # pH suitability (20 points)
    ph_min, ph_max = crop_data["ph_range"]
    if ph_min <= soil_info["ph"] <= ph_max:
        score += 20
    elif abs(soil_info["ph"] - ph_min) < 0.5 or abs(soil_info["ph"] - ph_max) < 0.5:
        score += 10
    
    # Season match (20 points)
    if season in crop_data["seasons"]:
        score += 20
    
    # Market demand (15 points)
    if crop_name in MARKET_PRICES:
        demand = MARKET_PRICES[crop_name]["demand"]
        if demand == "very high":
            score += 15
        elif demand == "high":
            score += 10
        elif demand == "medium":
            score += 5
    
    # Fertility match (10 points)
    if soil_info["fertility"] in ["High", "Very High"]:
        score += 10
    elif soil_info["fertility"] == "Medium":
        score += 5
    
    # Market trend bonus (5 points)
    if crop_name in MARKET_PRICES and MARKET_PRICES[crop_name]["trend"] == "rising":
        score += 5
    
    return min(score, 100)

def get_crop_recommendations(county, sublocation):
    soil_info = SOIL_DATA.get(county, {"type": "Loam", "ph": 6.5, "fertility": "Medium", "drainage": "Good"})
    season, season_desc = get_current_season()
    
    recommendations = []
    for crop_name, crop_data in CROP_DATABASE.items():
        score = calculate_crop_score(crop_name, crop_data, soil_info, season, season_desc)
        
        variety = crop_data["varieties"][0]
        maturity = crop_data["maturity_days"]
        
        market_info = MARKET_PRICES.get(crop_name, {"price": 0, "trend": "stable", "demand": "medium"})
        price = market_info["price"]
        trend = market_info["trend"]
        
        detail = f"Plant now · {maturity} days · KES {price:,}/bag · {trend.capitalize()} price"
        
        recommendations.append({
            "name": f"{crop_name} ({variety})",
            "detail": detail,
            "score": score
        })
    
    # Sort by score and return top 3
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    return recommendations[:3], soil_info, season, season_desc

# ── ENHANCED SYSTEM PROMPT ───────────────────────────────────────────────────
SYSTEM_PROMPT = """You are "Fahamu Shamba," an AI-powered agricultural assistant for Kenyan farmers.

CRITICAL RULES:
1. ALWAYS provide crop recommendations in this EXACT format when asked about crops to plant:

CROP: [Crop Name (Variety)]
DETAILS: [Planting info]
SCORE: [Number]

2. Use the soil data, weather, and market information provided in the context
3. Be conversational and friendly, use farmer's name if known
4. Respond in Swahili or English based on user preference
5. For non-agricultural questions, politely decline

Core Functions:
- Crop Recommendations (use provided soil/weather/market data)
- Pest & Disease Management
- Weather & Climate Updates
- Market Insights
- Image Analysis (identify crops, pests, diseases)

For USSD/SMS: Max 160 characters
For IVR: Short conversational sentences
For App: Full detailed responses"""

def ask_groq(user_message: str, mode: str = "app", session_id: str = "default", context_data: dict = None) -> str:
    mode_instruction = {
        "ussd": "Respond in under 160 characters. Plain text only.",
        "ivr": "Short conversational sentences for text-to-speech.",
        "app": "Full detailed response with structured format."
    }.get(mode, "")

    try:
        client = get_client()
        
        if session_id not in conversation_memory:
            conversation_memory[session_id] = []
        
        messages = [{"role": "system", "content": SYSTEM_PROMPT + f"\n\nMode: {mode_instruction}"}]
        
        # Add context data if provided
        if context_data:
            context_str = f"\n\nCONTEXT DATA:\n{json.dumps(context_data, indent=2)}"
            messages[0]["content"] += context_str
        
        messages.extend(conversation_memory[session_id][-10:])
        messages.append({"role": "user", "content": user_message})
        
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=600 if mode == "app" else 100,
            temperature=0.7
        )
        
        assistant_reply = response.choices[0].message.content.strip()
        
        conversation_memory[session_id].append({"role": "user", "content": user_message})
        conversation_memory[session_id].append({"role": "assistant", "content": assistant_reply})
        
        return assistant_reply
    except Exception as e:
        logger.error(f"Groq error: {e}")
        raise

def ask_groq_vision(image_bytes: bytes, mime_type: str, user_message: str, session_id: str = "default") -> str:
    try:
        client = get_client()
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if session_id in conversation_memory:
            messages.extend(conversation_memory[session_id][-5:])
        
        messages.append({
            "role": "user", 
            "content": [
                {"type": "text", "text": user_message or "Identify crop, pest, or disease in this image and provide advice."},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}
            ]
        })
        
        response = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=messages,
            max_tokens=600
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Vision error: {e}")
        raise

# ── API ENDPOINTS ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    county: str = None
    sublocation: str = None

@app.get("/health")
async def health():
    return {"status": "ok", "groq_key_set": bool(os.environ.get("GROQ_API_KEY"))}

@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        context_data = None
        
        # Check if this is a crop recommendation request
        msg_lower = req.message.lower()
        if any(keyword in msg_lower for keyword in ["best crop", "what to plant", "recommend", "should i plant"]):
            if req.county:
                recs, soil, season, season_desc = get_crop_recommendations(req.county, req.sublocation)
                context_data = {
                    "location": f"{req.sublocation}, {req.county}",
                    "soil": soil,
                    "season": season,
                    "season_description": season_desc,
                    "recommendations": recs
                }
        
        reply = ask_groq(req.message, mode="app", session_id=req.session_id, context_data=context_data)
        return {"reply": reply}
    except Exception as e:
        logger.error(f"/chat error: {e}")
        return {"reply": f"Error: {str(e)}"}

@app.post("/analyze-image")
async def analyze_image(
    image: UploadFile = File(...), 
    message: str = Form(default=""), 
    session_id: str = Form(default="default")
):
    try:
        image_bytes = await image.read()
        mime_type = image.content_type or "image/jpeg"
        reply = ask_groq_vision(image_bytes, mime_type, message, session_id)
        
        if session_id not in conversation_memory:
            conversation_memory[session_id] = []
        conversation_memory[session_id].append({"role": "user", "content": f"[Image] {message}"})
        conversation_memory[session_id].append({"role": "assistant", "content": reply})
        
        return {"reply": reply}
    except Exception as e:
        logger.error(f"/analyze-image error: {e}")
        return {"reply": f"Error: {str(e)}"}

@app.post("/get-recommendations")
async def get_recommendations(county: str = Form(...), sublocation: str = Form(...)):
    try:
        recs, soil, season, season_desc = get_crop_recommendations(county, sublocation)
        return {
            "recommendations": recs,
            "soil": soil,
            "season": season,
            "season_description": season_desc,
            "location": f"{sublocation}, {county}"
        }
    except Exception as e:
        logger.error(f"/get-recommendations error: {e}")
        return {"error": str(e)}

@app.post("/ussd", response_class=PlainTextResponse)
async def ussd(sessionId: str = Form(...), serviceCode: str = Form(...), phoneNumber: str = Form(...), text: str = Form("")):
    if text == "":
        return "CON Welcome to Fahamu Shamba\n1. Best Crop to Plant\n2. Pest & Disease Tips\n3. Weather Update\n4. Market Prices"
    elif text == "1":
        return "CON Enter your county (e.g. Nakuru):"
    elif text == "2":
        return "CON Enter your crop name (e.g. maize):"
    elif text == "3":
        return "CON Enter your county:"
    elif text == "4":
        return "CON Enter crop name:"
    else:
        parts = text.split("*")
        menu = parts[0]
        user_input = parts[-1] if len(parts) > 1 else ""
        
        if menu == "1" and user_input:
            county = user_input.strip().title()
            if county in SOIL_DATA:
                recs, _, _, _ = get_crop_recommendations(county, "")
                top = recs[0]
                return f"END Top crop: {top['name']}\n{top['detail']}"
            return f"END Plant maize, beans or sorghum in {user_input}"
        
        queries = {
            "2": f"Pest management for {user_input}",
            "3": f"Weather advice for {user_input} Kenya",
            "4": f"Market price for {user_input}"
        }
        query = queries.get(menu, user_input)
        advice = ask_groq(query, mode="ussd")
        return f"END {advice}"

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html") as f:
        return f.read()
