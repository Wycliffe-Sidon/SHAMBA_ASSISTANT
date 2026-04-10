from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from groq import Groq
import os
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

If asked non-agricultural questions, respond: "I am your agricultural assistant. Please ask me about farming, crops, weather, or markets."

For USSD/SMS: Keep responses under 160 characters, plain text only.
For IVR: Use conversational sentences suitable for text-to-speech.
For App: Full detailed chatbot-style responses."""


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
