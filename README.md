# SHAMBA ASSISTANT

SHAMBA ASSISTANT is a production-ready, voice-first agricultural web app for East African farmers. It combines Anthropic Claude, OpenWeatherMap, SoilGrids, fallback/live market prices, browser voice input/output, and Twilio voice webhooks in one Node.js + Express deployment.

## Features

- Siri-like multilingual farming assistant with strict `EN / SW / LUO` modes
- Claude model `claude-sonnet-4-20250514` behind a secure backend proxy
- Live weather and 7-day forecast via OpenWeatherMap
- Soil analysis via SoilGrids with pH, clay, sand, organic carbon, texture, and fertility summary
- Market price ticker with configurable external feed and built-in East Africa fallback table
- Voice input with Web Speech API, continuous listening toggle, and speech interruption
- Voice output with speech synthesis and Luo fallback voice selection
- Twilio voice webhook loop for incoming farming calls
- PWA support with `manifest.json` and `sw.js`

## Project Structure

```text
shamba-assistant/
  public/
    index.html
    manifest.json
    sw.js
  routes/
    api.js
    voice.js
  server.js
  .env
  .env.example
  package.json
  README.md
```

## Environment Variables

Create `.env` from `.env.example` and fill in:

```env
ANTHROPIC_API_KEY=your_key_here
OPENWEATHER_API_KEY=your_key_here
TWILIO_ACCOUNT_SID=your_sid_here
TWILIO_AUTH_TOKEN=your_token_here
TWILIO_PHONE_NUMBER=+254700000000
MARKET_PRICES_URL=
PORT=3000
```

Notes:

- `MARKET_PRICES_URL` is optional. If set, `/api/prices` will try that feed first.
- If `MARKET_PRICES_URL` is not set or fails, the app falls back to a realistic weekly East Africa price table in `routes/api.js`.

## Local Setup

1. Install Node.js 18 or newer.
2. Install dependencies:

```bash
npm install
```

3. Start the server:

```bash
node server.js
```

4. Open `http://localhost:3000`.

The app is designed for Chrome desktop and Chrome for Android. HTTPS is required in production for microphone access.

## API Endpoints

- `POST /api/chat` - Claude chat proxy with live location/weather/soil/prices injected into the system prompt
- `GET /api/weather` - OpenWeatherMap current weather + forecast proxy
- `GET /api/soil` - SoilGrids soil summary proxy
- `GET /api/prices` - Market prices JSON
- `GET /api/config` - Frontend runtime config
- `POST /voice/incoming` - Twilio greeting + gather webhook
- `POST /voice/respond` - Twilio speech loop webhook
- `GET /health` - health check

## Twilio Configuration

Set your Twilio phone number voice webhook to:

```text
https://your-domain.com/voice/incoming
```

Twilio flow:

1. Twilio calls `POST /voice/incoming`
2. The server returns a greeting and a `<Gather input="speech">`
3. Twilio posts recognized speech to `POST /voice/respond`
4. The server sends the speech to Claude and replies with TwiML `<Say>` plus another `<Gather>`
5. The loop continues until the caller hangs up

You can pass optional `lang` and `location` query parameters when testing:

```text
https://your-domain.com/voice/incoming?lang=sw&location=Nairobi%2C%20Kenya
```

## Deployment

You can deploy to Railway, Render, or Heroku-style Node hosting.

### Vercel

This repo now includes:

- `vercel.json`
- `api/index.js`

They route Vercel traffic into the Express app as a Node serverless function while still serving `public/` as static assets.

Deploy with:

```bash
npx vercel
```

For production redeploy:

```bash
npx vercel --prod
```

Set these environment variables in the Vercel project settings:

- `ANTHROPIC_API_KEY`
- `OPENWEATHER_API_KEY`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `MARKET_PRICES_URL` if used

### Render

- `buildCommand`: `npm install`
- `startCommand`: `node server.js`
- Add all environment variables from `.env.example`
- Ensure HTTPS is enabled

The included `render.yaml` can be used as a starting point.

### Railway / Heroku

- Set the same environment variables
- Expose port `3000` or honor the platform `PORT`
- Point the root service to `server.js`

## PWA Install

The app includes:

- `public/manifest.json`
- `public/sw.js`

On Android Chrome, farmers can install it from the browser menu like a native app.

## Important Behavior

- The assistant responds only in the currently selected language.
- Non-agriculture questions are refused warmly in the active language.
- Language switch clears the current web chat session and starts a new greeting.
- Crop recommendations are instructed to return exactly top 3 ranked options using weather, soil, and market prices.
- Browser geolocation is used on first load when available.

## Security

- API keys stay on the server
- `helmet` is enabled
- `cors` is enabled
- `/api/chat` is rate-limited to 30 requests per minute

## GitHub Push

To push this project:

```bash
git add .
git commit -m "Build SHAMBA ASSISTANT voice-first farming web app"
git push origin HEAD
```
