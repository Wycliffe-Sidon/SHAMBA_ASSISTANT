const express = require("express");
const axios = require("axios");

const router = express.Router();

const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const DEFAULT_MODEL = "claude-sonnet-4-20250514";
const DEFAULT_LANGUAGE = "en";
const DEFAULT_LOCATION = "Siaya County, Kenya";

const LANGUAGE_CONFIG = {
  en: {
    label: "English",
    greeting: "Hello. I am Shamba Assistant for Siaya County. Ask me about crops, pests, diseases, markets, livestock, or soil.",
    prompt: "Please say your farming question.",
    onlyAg: "I can only help with agricultural questions for Siaya County. Please ask a farming question."
  },
  sw: {
    label: "Kiswahili",
    greeting: "Habari. Mimi ni Shamba Assistant wa Kaunti ya Siaya. Uliza kuhusu mazao, wadudu, magonjwa, soko, mifugo, au udongo.",
    prompt: "Tafadhali sema swali lako la kilimo.",
    onlyAg: "Naweza kusaidia tu maswali ya kilimo ya Kaunti ya Siaya. Tafadhali uliza swali la kilimo."
  },
  luo: {
    label: "Luo-Dholuo",
    greeting: "Misawa. An Shamba Assistant mar Siaya County. Penja kuom cham, tuoche, tuo, soko, dhok mar dhiang', kata ngom.",
    prompt: "Wach penji mari mar lemo.",
    onlyAg: "Anyalo konyi gi penjo mag lemo mar Siaya County kende. Penj wach mar lemo."
  }
};

const AGRI_REGEX = /\b(crop|farm|soil|pest|disease|plant|seed|harvest|fertilizer|pesticide|irrigat|maize|bean|sorghum|cassava|sweet potato|tomato|kale|sukuma|vegetable|weather|rain|market|price|acre|yield|weed|spray|fungus|fungal|blight|aphid|locust|stem borer|animal|chicken|cow|goat|livestock|poultry|feed|pasture|manure|compost|organic|shamba|kilimo|mbegu|mavuno|udongo|chakula|lemo|cham|kuon)\b/i;

function getLanguage(language) {
  return LANGUAGE_CONFIG[language] ? language : DEFAULT_LANGUAGE;
}

function isAgriculturalQuery(message = "") {
  return AGRI_REGEX.test(String(message || ""));
}

async function anthropicRequest(payload) {
  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error("ANTHROPIC_API_KEY is not configured.");
  }

  const response = await axios.post(ANTHROPIC_URL, payload, {
    headers: {
      "Content-Type": "application/json",
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01"
    },
    timeout: 60000
  });

  return response.data;
}

function formatSystemPrompt({ language, location, weather, soil, prices }) {
  const lang = getLanguage(language);
  return [
    "You are Shamba Assistant, an agricultural AI agent EXCLUSIVELY for Siaya County, Kenya.",
    `You MUST respond ONLY in ${LANGUAGE_CONFIG[lang].label}.`,
    "Only answer agricultural questions about crops, pests, diseases, livestock, soil, weather impact on farming, irrigation, fertilizers, and crop market prices.",
    "Refuse non-agricultural questions politely in the current language.",
    "Always factor in Siaya County conditions: Lake Victoria basin, red clay Vertisol soils, pH 5.5-6.5, rainfall roughly 1200-1800 mm yearly.",
    `Location context: ${location || DEFAULT_LOCATION}`,
    `Weather context: ${JSON.stringify(weather || {})}`,
    `Soil context: ${JSON.stringify(soil || {})}`,
    `Price context: ${JSON.stringify(prices || [])}`
  ].join("\n");
}

async function buildAssistantContext({ location }) {
  return {
    weather: {
      location: location || DEFAULT_LOCATION,
      current: {
        temperatureC: 26,
        humidity: 74,
        rainfallMm: 1400
      }
    },
    soil: {
      summary: {
        ph: 5.8,
        type: "Clay (Vertisol)"
      }
    },
    prices: [
      { crop: "Maize", low: 3200, high: 4300, market: "Siaya/Kisumu" },
      { crop: "Beans", low: 7000, high: 9800, market: "Siaya/Kisumu" },
      { crop: "Sorghum", low: 4200, high: 5600, market: "Siaya/Bondo" }
    ]
  };
}

function validateMessages(messages) {
  return Array.isArray(messages)
    && messages.every(item => item && typeof item.role === "string" && Array.isArray(item.content));
}

function readStreamToString(stream) {
  return new Promise((resolve, reject) => {
    let output = "";
    stream.setEncoding("utf8");
    stream.on("data", chunk => {
      output += chunk;
    });
    stream.on("end", () => resolve(output));
    stream.on("error", reject);
  });
}

router.get("/config", (_req, res) => {
  res.json({
    serverProxyAvailable: Boolean(process.env.ANTHROPIC_API_KEY),
    defaultModel: DEFAULT_MODEL,
    defaultLanguage: DEFAULT_LANGUAGE,
    defaultLocation: DEFAULT_LOCATION
  });
});

router.post("/chat", async (req, res) => {
  try {
    const {
      model = DEFAULT_MODEL,
      max_tokens = 1000,
      system = "",
      messages = [],
      stream = true
    } = req.body || {};

    if (!validateMessages(messages)) {
      return res.status(400).json({ error: "A valid Anthropic messages array is required." });
    }

    if (!process.env.ANTHROPIC_API_KEY) {
      return res.status(500).json({ error: "ANTHROPIC_API_KEY is not configured on the server." });
    }

    const payload = {
      model,
      max_tokens,
      system,
      messages,
      stream: Boolean(stream)
    };

    if (!stream) {
      const data = await anthropicRequest(payload);
      return res.json(data);
    }

    const upstream = await axios.post(ANTHROPIC_URL, payload, {
      headers: {
        "Content-Type": "application/json",
        "x-api-key": process.env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01"
      },
      responseType: "stream",
      timeout: 0,
      validateStatus: () => true
    });

    if (upstream.status >= 400) {
      const detail = await readStreamToString(upstream.data);
      return res.status(upstream.status).json({ error: detail || "Anthropic streaming request failed." });
    }

    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    if (typeof res.flushHeaders === "function") {
      res.flushHeaders();
    }

    req.on("close", () => {
      upstream.data.destroy();
    });

    upstream.data.on("error", error => {
      if (!res.writableEnded) {
        res.write(`data: ${JSON.stringify({ type: "error", error: { message: error.message || "Streaming failed." } })}\n\n`);
        res.end();
      }
    });

    upstream.data.pipe(res);
  } catch (error) {
    const detail = error.response?.data || error.message || "Chat request failed.";
    res.status(error.response?.status || 500).json({
      error: typeof detail === "string" ? detail : JSON.stringify(detail)
    });
  }
});

module.exports = router;
module.exports.helpers = {
  DEFAULT_LANGUAGE,
  DEFAULT_LOCATION,
  LANGUAGE_CONFIG,
  anthropicRequest,
  buildAssistantContext,
  formatSystemPrompt,
  getLanguage,
  isAgriculturalQuery
};
