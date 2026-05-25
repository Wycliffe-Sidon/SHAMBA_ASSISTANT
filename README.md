# SHAMBA ASSISTANT

Shamba Assistant is a Siaya County focused agricultural chatbot served as a single HTML app with inline CSS and JavaScript. The browser UI handles chat, crop recommendations, market tables, image upload, and voice features, while the Node server only serves the page and proxies Anthropic requests securely.

## Current Stack

- Single-file frontend: `public/index.html`
- Express server: `server.js`
- Anthropic proxy: `routes/api.js`
- Model: `claude-sonnet-4-20250514`
- Streaming: SSE
- Voice: Web Speech API in-browser

## What Was Removed

The older multi-surface app layers were cleaned out so this repo aligns with the current Shamba Assistant build:

- Old Python app files
- Old `static/` HTML
- Legacy voice webhook route
- Unused PWA files
- Unused image asset from the previous UI

## Local Run

1. Install dependencies:

```bash
npm install
```

2. Set environment variables:

```env
ANTHROPIC_API_KEY=your_key_here
PORT=3000
```

3. Start the server:

```bash
node server.js
```

4. Open:

```text
http://localhost:3000
```

## Browser-Only Option

If you want the HTML file to call Anthropic directly when opened outside the server, set `DIRECT_ANTHROPIC_API_KEY` at the top of `public/index.html`. For hosted use, keep that blank and rely on the server-side `ANTHROPIC_API_KEY`.

## API Endpoints

- `GET /api/config`
- `POST /api/chat`
- `GET /health`

## Deployment

### Render

- `buildCommand`: `npm install`
- `startCommand`: `node server.js`
- required env: `ANTHROPIC_API_KEY`

### Vercel

This repo still includes:

- `vercel.json`
- `api/index.js`

They forward traffic into the same Express app.
