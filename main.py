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

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_LANGUAGE = "en"
DEFAULT_LOCATION = "Siaya County, Kenya"

app = FastAPI(title="Shamba Assistant")


def json_error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def get_anthropic_headers() -> dict[str, str]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured on the server.")

    return {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


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
        "serverProxyAvailable": bool(os.getenv("ANTHROPIC_API_KEY")),
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
        return json_error("A valid Anthropic messages array is required.", 400)

    model = payload.get("model") or DEFAULT_MODEL
    max_tokens = payload.get("max_tokens") or 1000
    system = payload.get("system") or ""
    stream = bool(payload.get("stream", True))

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "stream": stream,
    }

    try:
        headers = get_anthropic_headers()
    except RuntimeError as error:
        return json_error(str(error), 500)

    if not stream:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(ANTHROPIC_URL, headers=headers, json=body)
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
                async with client.stream("POST", ANTHROPIC_URL, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        detail = await response.aread()
                        error_text = detail.decode("utf-8", errors="replace") or "Anthropic streaming request failed."
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
