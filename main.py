import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
INDEX_FILE = PUBLIC_DIR / "index.html"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
DEFAULT_LANGUAGE = "en"
DEFAULT_LOCATION = "Siaya County, Kenya"

app = FastAPI(title="Shamba Assistant")


def json_error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def get_groq_headers() -> dict[str, str]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured on the server.")

    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def normalize_groq_content(content: Any) -> Any:
    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return ""

    normalized: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue

        if block.get("type") == "text":
            normalized.append({"type": "text", "text": str(block.get("text", ""))})
            continue

        if block.get("type") == "image":
            source = block.get("source") or {}
            data = source.get("data") or ""
            if not data:
                continue
            normalized.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{source.get('media_type', 'image/jpeg')};base64,{data}"
                    },
                }
            )
            continue

        if block.get("type") == "image_url" and isinstance(block.get("image_url"), dict):
            url = block["image_url"].get("url")
            if url:
                normalized.append({"type": "image_url", "image_url": {"url": str(url)}})

    if not normalized:
        return ""

    if len(normalized) == 1 and normalized[0]["type"] == "text":
        return normalized[0]["text"]

    return normalized


def to_groq_messages(messages: list[Any], system: str) -> list[dict[str, Any]]:
    groq_messages: list[dict[str, Any]] = []
    has_system_message = any(isinstance(item, dict) and item.get("role") == "system" for item in messages)

    if system and not has_system_message:
        groq_messages.append({"role": "system", "content": str(system)})

    for item in messages:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            continue
        groq_messages.append(
            {
                "role": item["role"],
                "content": normalize_groq_content(item.get("content")),
            }
        )

    return groq_messages


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "shamba-assistant",
    }


@app.get("/app-config")
@app.get("/api/config")
async def app_config() -> dict[str, Any]:
    return {
        "serverProxyAvailable": bool(os.getenv("GROQ_API_KEY")),
        "defaultModel": DEFAULT_MODEL,
        "defaultLanguage": DEFAULT_LANGUAGE,
        "defaultLocation": DEFAULT_LOCATION,
    }


@app.post("/api/chat")
async def chat(request: Request) -> Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return json_error("A valid JSON body is required.", 400)

    if not isinstance(payload, dict):
        return json_error("A valid JSON object is required.", 400)

    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return json_error("A valid chat messages array is required.", 400)

    model = payload.get("model") or DEFAULT_MODEL
    max_tokens = payload.get("max_tokens") or payload.get("max_completion_tokens") or 1000
    system = payload.get("system") or ""
    stream = bool(payload.get("stream", True))

    body = {
        "model": model,
        "max_completion_tokens": max_tokens,
        "messages": to_groq_messages(messages, system),
        "stream": stream,
    }

    try:
        headers = get_groq_headers()
    except RuntimeError as error:
        return json_error(str(error), 500)

    if not stream:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(GROQ_URL, headers=headers, json=body)
            except httpx.HTTPError as error:
                return json_error(str(error), 502)

        detail: Any
        try:
            detail = response.json()
        except ValueError:
            detail = response.text

        if response.status_code >= 400:
            return json_error(
                detail if isinstance(detail, str) else json.dumps(detail),
                response.status_code,
            )

        return JSONResponse(detail)

    async def event_stream():
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream("POST", GROQ_URL, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        detail = await response.aread()
                        error_text = detail.decode("utf-8", errors="replace") or "Groq streaming request failed."
                        yield f"data: {json.dumps({'type': 'error', 'error': {'message': error_text}})}\n\n"
                        return

                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk
            except httpx.HTTPError as error:
                yield f"data: {json.dumps({'type': 'error', 'error': {'message': str(error)}})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/{full_path:path}")
async def spa(full_path: str) -> Response:
    if full_path.startswith("api/"):
        return json_error("Not found.", 404)

    file_path = PUBLIC_DIR / full_path
    if full_path and file_path.is_file():
        return FileResponse(file_path)

    return FileResponse(INDEX_FILE)
