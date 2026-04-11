from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from groq import Groq
import os
import base64
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_client():
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY environment variable is not set")
    return Groq(api_key=key)

SYSTEM_PROMPT = """You are "Fahamu Shamba," an AI-powered agricultural assistant built for farmers in Kenya.
Your role is to provide ONLY agricultural guidance and ignore or politely decline non-agricultural queries.

Core Functions:
1. Crop Recommendations - advise on best crops based on soil, weather, season, location, market demand.
2. Pest & Disease Management - preventive measures and treatments.
3. Weather & Climate Updates - interpret rainfall, drought risk, temperature for planting/harvesting.
4. Market Insights - current prices and best time to sell.
5. Farmer Interaction - respond in Swahili or English based on farmer preference.

When providing crop recommendations, structure your response as follows:
- Start with a brief introduction about the location and season
- Then list 3 recommended crops in this EXACT format:
  CROP: [Crop Name]
  DETAILS: [Brief planting info]
  SCORE: [Confidence percentage]

Example:
Based on your location in Siaya County during the long rains season, here are my recommendations:

CROP: Maize (WEMA DT)
DETAILS: Plant now · Harvest in 90 days · High market demand
SCORE: 94

CROP: Beans (KK15)
DETAILS: Intercrop with maize · 75 days · Good price
SCORE: 87

CROP: Sorghum (Seredo)
DETAILS: Drought-tolerant · 120 days · Stable price
SCORE: 81

If asked non-agricultural questions, respond: "I am your agricultural assistant. Please ask me about farming, crops, weather, or markets."

For USSD/SMS: Keep responses under 160 characters, plain text only.
For IVR: Use conversational sentences suitable for text-to-speech.
For App: Full detailed responses with structured crop recommendations."""


def ask_groq(user_message: str, mode: str = "app") -> str:
    mode_instruction = {
        "ussd": "Respond in under 160 characters. Plain text only. No emojis.",
        "ivr": "Respond in short conversational sentences suitable for text-to-speech. No special characters.",
        "app": "Respond with full detail, context, and helpful formatting."
    }.get(mode, "")

    try:
        client = get_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT + f"\n\nMode: {mode_instruction}"},
                {"role": "user", "content": user_message}
            ],
            max_tokens=500 if mode == "app" else 100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Groq error: {e}")
        raise


def ask_groq_vision(image_bytes: bytes, mime_type: str, user_message: str) -> str:
    try:
        client = get_client()
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": user_message or "Identify any pest, disease, or crop condition visible in this image. Provide agricultural advice."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}
                ]}
            ],
            max_tokens=600
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Groq vision error: {e}")
        raise


# ── App Chat Endpoint ──────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str

@app.get("/health")
async def health():
    key = os.environ.get("GROQ_API_KEY")
    return {"status": "ok", "groq_key_set": bool(key)}

@app.get("/test")
async def test_groq():
    try:
        reply = ask_groq("What is the best crop to plant in Kenya?", mode="app")
        return {"status": "ok", "reply": reply}
    except Exception as e:
        logger.error(f"/test error: {e}")
        return {"status": "error", "detail": str(e)}

@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        reply = ask_groq(req.message, mode="app")
        return {"reply": reply}
    except Exception as e:
        logger.error(f"/chat error: {e}")
        return {"reply": f"Error: {str(e)}"}


@app.post("/analyze-image")
async def analyze_image(image: UploadFile = File(...), message: str = Form(default="")):
    try:
        image_bytes = await image.read()
        mime_type = image.content_type or "image/jpeg"
        reply = ask_groq_vision(image_bytes, mime_type, message)
        return {"reply": reply}
    except Exception as e:
        logger.error(f"/analyze-image error: {e}")
        return {"reply": f"Error analyzing image: {str(e)}"}


# ── USSD Endpoint (Africa's Talking) ──────────────────────────────────────────
@app.post("/ussd", response_class=PlainTextResponse)
async def ussd(
    sessionId: str = Form(...),
    serviceCode: str = Form(...),
    phoneNumber: str = Form(...),
    text: str = Form("")
):
    if text == "":
        response = "CON Welcome to Fahamu Shamba\n1. Best Crop to Plant\n2. Pest & Disease Tips\n3. Weather Update\n4. Market Prices"
    elif text == "1":
        response = "CON Enter your location and soil type (e.g. Nakuru, loam):"
    elif text == "2":
        response = "CON Enter your crop name (e.g. maize):"
    elif text == "3":
        response = "CON Enter your county for weather advice (e.g. Kisumu):"
    elif text == "4":
        response = "CON Enter crop to check market price (e.g. tomatoes):"
    else:
        parts = text.split("*")
        menu = parts[0]
        user_input = parts[-1] if len(parts) > 1 else ""

        queries = {
            "1": f"Best crop to plant in {user_input}",
            "2": f"Pest and disease management for {user_input}",
            "3": f"Weather and planting advice for {user_input} county Kenya",
            "4": f"Current market price and best time to sell {user_input} in Kenya"
        }
        query = queries.get(menu, user_input)
        advice = ask_groq(query, mode="ussd")
        response = f"END {advice}"

    return response


# ── IVR Endpoint (Africa's Talking / Twilio) ──────────────────────────────────
@app.post("/ivr")
async def ivr(request: Request):
    body = await request.form()
    digits = body.get("dtmfDigits", "") or body.get("Digits", "")
    caller = body.get("callerNumber", "") or body.get("From", "")

    ivr_queries = {
        "1": "What is the best crop to plant in Kenya right now?",
        "2": "What are common crop pests and diseases in Kenya and how to treat them?",
        "3": "What is the current weather forecast and planting advice for Kenyan farmers?",
        "4": "What are current market prices for common crops in Kenya?"
    }

    if not digits:
        # Africa's Talking IVR XML
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <GetDigits timeout="30" finishOnKey="#" callbackUrl="/ivr">
    <Say>Welcome to Fahamu Shamba, your farming advisor. Press 1 for crop recommendations. Press 2 for pest and disease tips. Press 3 for weather updates. Press 4 for market prices. Then press hash.</Say>
  </GetDigits>
</Response>"""
        return HTMLResponse(content=xml, media_type="application/xml")

    query = ivr_queries.get(digits, f"Agricultural advice about: {digits}")
    advice = ask_groq(query, mode="ivr")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>{advice}</Say>
  <Say>Thank you for using Fahamu Shamba. Goodbye.</Say>
</Response>"""
    return HTMLResponse(content=xml, media_type="application/xml")


# ── Serve UI ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html") as f:
        return f.read()
