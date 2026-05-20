const express = require("express");
const axios = require("axios");

const router = express.Router();

const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const OPENWEATHER_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather";
const OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast";
const OPENWEATHER_GEOCODE_URL = "http://api.openweathermap.org/geo/1.0/direct";
const OPENWEATHER_REVERSE_URL = "http://api.openweathermap.org/geo/1.0/reverse";
const SOILGRIDS_URL = "https://rest.soilgrids.org/soilgrids/v2.0/properties/query";

const DEFAULT_LOCATION = "Nairobi, Kenya";
const DEFAULT_LANGUAGE = "en";
const ANTHROPIC_MODEL = "claude-sonnet-4-20250514";

const LANGUAGE_CONFIG = {
  en: {
    label: "English",
    locale: "en-US",
    greeting: "Hello. I am Shamba Assistant. Ask me anything about crops, soil, weather, livestock, pests, irrigation, fertilizers, or rural market prices.",
    prompt: "Please say your farming question after the tone.",
    onlyAg: "I am an agricultural assistant only. Please ask me about crops, livestock, soil, weather for farming, irrigation, fertilizers, pest control, or rural market prices.",
    locationUpdated: location => `I have updated your farm context to ${location}. Weather, soil, and market prices are refreshed.`,
  },
  sw: {
    label: "Kiswahili",
    locale: "sw-KE",
    greeting: "Habari. Mimi ni Shamba Assistant. Uliza kuhusu mazao, udongo, hali ya hewa, mifugo, wadudu, umwagiliaji, mbolea, au bei za soko la mazao.",
    prompt: "Tafadhali sema swali lako la kilimo baada ya mlio.",
    onlyAg: "Mimi ni msaidizi wa kilimo pekee. Tafadhali uliza kuhusu mazao, mifugo, udongo, hali ya hewa ya kilimo, umwagiliaji, mbolea, wadudu, au bei za soko la mazao.",
    locationUpdated: location => `Nimesasisha taarifa za shamba lako hadi ${location}. Hali ya hewa, udongo, na bei za soko zimehuishwa.`,
  },
  luo: {
    label: "Luo-Dholuo",
    locale: "luo",
    greeting: "Misawa. An Shamba Assistant. Penja kuom mazao, ngom, koth, dhiang', kudho pi, yath mar puodho, tuo mar yath, kata bei mar soko.",
    prompt: "Wach penji mari mar puodho bang' dwol.",
    onlyAg: "An jakony mar puodho kende. Penja kuom mazao, dhiang', ngom, koth mar puodho, kudho pi, yath mar puodho, tua kod chwiri mar yath, kata bei mar soko.",
    locationUpdated: location => `Aseketo weche mar puodhi e ${location}. Koth, ngom, gi bei mar soko osebedo manyien.`,
  },
};

const UI_SUGGESTIONS = {
  en: [
    "What are the top 3 crops to plant in Nairobi right now?",
    "How much rain is expected this week for maize farming?",
    "Show me the current bean and onion market prices.",
    "My kale leaves are curling. What pest could be causing it?",
    "How should I improve this soil before planting tomatoes?",
  ],
  sw: [
    "Ni mazao gani matatu bora kupanda Nairobi sasa hivi?",
    "Mvua ya wiki hii inatosha kwa kilimo cha mahindi?",
    "Nionyeshe bei ya sasa ya maharagwe na vitunguu sokoni.",
    "Majani ya sukuma yanajikunja. Inaweza kuwa mdudu gani?",
    "Niboresheje udongo huu kabla ya kupanda nyanya?",
  ],
  luo: [
    "Ma en mazao adek maber mapile e Nairobi sani?",
    "Koth mar wiki ni biro romo ni puodho bel?",
    "Nyisa bei mar njahe gi kitung'u sani e soko.",
    "Pot sukuma tedo. Nyalo bedo ni chwiri mane?",
    "Abiro yubo ngom ni ang'o kapok apando nyanya?",
  ],
};

const FALLBACK_MARKET_PRICES = [
  { crop: "Maize", unit: "kg", price: 58, market: "Nairobi", trend: "stable" },
  { crop: "Beans", unit: "kg", price: 132, market: "Kisumu", trend: "up" },
  { crop: "Tomatoes", unit: "kg", price: 74, market: "Nairobi", trend: "up" },
  { crop: "Kale", unit: "kg", price: 48, market: "Nakuru", trend: "stable" },
  { crop: "Onions", unit: "kg", price: 88, market: "Nairobi", trend: "up" },
  { crop: "Sorghum", unit: "kg", price: 64, market: "Eldoret", trend: "stable" },
  { crop: "Millet", unit: "kg", price: 79, market: "Kisumu", trend: "up" },
  { crop: "Sweet Potato", unit: "kg", price: 55, market: "Busia", trend: "stable" },
  { crop: "Sunflower", unit: "kg", price: 71, market: "Kitale", trend: "stable" },
  { crop: "Banana", unit: "kg", price: 29, market: "Kisii", trend: "up" },
];

function getLanguage(language) {
  return LANGUAGE_CONFIG[language] ? language : DEFAULT_LANGUAGE;
}

function getSessionStore(req) {
  return req.app.locals.sessions;
}

function getSession(store, sessionId) {
  const key = sessionId || "default";
  if (!store.has(key)) {
    store.set(key, {
      history: [],
      language: DEFAULT_LANGUAGE,
      location: DEFAULT_LOCATION,
      context: null,
    });
  }
  return store.get(key);
}

function isAgriculturalQuery(message = "") {
  const lowered = message.toLowerCase();
  const keywords = [
    "farm", "farming", "crop", "crops", "maize", "beans", "soil", "weather",
    "rain", "pest", "disease", "fertilizer", "fertiliser", "livestock", "cow",
    "goat", "chicken", "irrigation", "market", "seed", "harvest", "yield",
    "tomato", "onion", "banana", "sorghum", "millet", "sweet potato", "sunflower",
    "shamba", "kilimo", "mazao", "mbegu", "mvua", "wadudu", "mifugo", "soko",
    "udongo", "umwagiliaji", "mbolea", "ng'ombe", "kuku",
    "puodho", "mazao", "ngom", "koth", "dhiang", "yath", "soko", "pi",
  ];
  const greetings = ["hello", "hi", "habari", "misawa", "sasa", "morning", "afternoon"];
  return greetings.includes(lowered.trim()) || keywords.some(keyword => lowered.includes(keyword));
}

function detectIntent(message = "") {
  const lowered = message.toLowerCase();
  if (/(price|prices|market|sell|buyer|soko|bei)/.test(lowered)) {
    return "market";
  }
  if (/(weather|rain|forecast|temperature|wind|mvua|hali ya hewa|koth)/.test(lowered)) {
    return "weather";
  }
  if (/(soil|fertilizer|fertiliser|manure|ph|mbolea|udongo|ngom)/.test(lowered)) {
    return "soil";
  }
  if (/(pest|disease|spray|armyworm|fungus|wadudu|ugonjwa|tuo|chwiri)/.test(lowered)) {
    return "pests";
  }
  if (/(plant|crop recommendation|what should i plant|mazao|panda|seed|yield|harvest|puodho)/.test(lowered)) {
    return "crops";
  }
  return "general";
}

async function anthropicRequest(payload) {
  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error("ANTHROPIC_API_KEY is not configured.");
  }
  const response = await axios.post(ANTHROPIC_URL, payload, {
    headers: {
      "Content-Type": "application/json",
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    timeout: 30000,
  });
  return response.data;
}

async function geocodeLocation(location) {
  if (!process.env.OPENWEATHER_API_KEY) {
    throw new Error("OPENWEATHER_API_KEY is not configured.");
  }
  const response = await axios.get(OPENWEATHER_GEOCODE_URL, {
    params: {
      q: location || DEFAULT_LOCATION,
      limit: 1,
      appid: process.env.OPENWEATHER_API_KEY,
    },
    timeout: 15000,
  });
  const [entry] = response.data || [];
  if (!entry) {
    throw new Error(`Could not geocode location: ${location}`);
  }
  return {
    name: entry.name,
    state: entry.state || "",
    country: entry.country,
    lat: entry.lat,
    lon: entry.lon,
    label: [entry.name, entry.state, entry.country].filter(Boolean).join(", "),
  };
}

async function reverseGeocode(lat, lon) {
  if (!process.env.OPENWEATHER_API_KEY) {
    throw new Error("OPENWEATHER_API_KEY is not configured.");
  }
  const response = await axios.get(OPENWEATHER_REVERSE_URL, {
    params: {
      lat,
      lon,
      limit: 1,
      appid: process.env.OPENWEATHER_API_KEY,
    },
    timeout: 15000,
  });
  const [entry] = response.data || [];
  if (!entry) {
    return { lat, lon, label: DEFAULT_LOCATION };
  }
  return {
    name: entry.name,
    state: entry.state || "",
    country: entry.country,
    lat,
    lon,
    label: [entry.name, entry.state, entry.country].filter(Boolean).join(", "),
  };
}

async function resolveLocation({ location, lat, lon }) {
  if (typeof lat === "number" && typeof lon === "number" && !Number.isNaN(lat) && !Number.isNaN(lon)) {
    return reverseGeocode(lat, lon);
  }
  return geocodeLocation(location || DEFAULT_LOCATION);
}

function summarizeForecast(list = []) {
  const daily = [];
  for (let index = 0; index < list.length && daily.length < 7; index += 8) {
    const item = list[index];
    if (!item) {
      continue;
    }
    daily.push({
      date: item.dt_txt,
      tempC: item.main?.temp ?? null,
      humidity: item.main?.humidity ?? null,
      windSpeed: item.wind?.speed ?? null,
      description: item.weather?.[0]?.description ?? "",
      rainProbability: item.pop ?? 0,
    });
  }
  return daily;
}

async function fetchWeatherContext({ location, lat, lon }) {
  const resolved = await resolveLocation({ location, lat, lon });
  const commonParams = {
    appid: process.env.OPENWEATHER_API_KEY,
    units: "metric",
    lat: resolved.lat,
    lon: resolved.lon,
  };
  const [currentResponse, forecastResponse] = await Promise.all([
    axios.get(OPENWEATHER_CURRENT_URL, { params: commonParams, timeout: 20000 }),
    axios.get(OPENWEATHER_FORECAST_URL, { params: commonParams, timeout: 20000 }),
  ]);
  const current = currentResponse.data;
  const forecast = forecastResponse.data;
  return {
    location: resolved.label,
    coordinates: { lat: resolved.lat, lon: resolved.lon },
    current: {
      temperatureC: current.main?.temp ?? null,
      description: current.weather?.[0]?.description ?? "",
      humidity: current.main?.humidity ?? null,
      windSpeed: current.wind?.speed ?? null,
      rainProbability: forecast.list?.[0]?.pop ?? 0,
    },
    forecast: summarizeForecast(forecast.list || []),
    rawCurrent: current,
    rawForecast: forecast,
  };
}

function deriveSoilTexture(clay, sand) {
  if (clay >= 35) {
    return "clay";
  }
  if (sand >= 60) {
    return "sandy";
  }
  return "loam";
}

function deriveFertilityRating(organicCarbon) {
  if (organicCarbon >= 25) {
    return "High";
  }
  if (organicCarbon >= 12) {
    return "Medium";
  }
  return "Low";
}

function readSoilValue(layer) {
  return layer?.depths?.find(item => item.range?.top_depth === 0 && item.range?.bottom_depth === 5)?.values?.mean
    ?? layer?.depths?.[0]?.values?.mean
    ?? null;
}

async function fetchSoilContext({ location, lat, lon }) {
  const resolved = await resolveLocation({ location, lat, lon });
  const response = await axios.get(SOILGRIDS_URL, {
    params: {
      lon: resolved.lon,
      lat: resolved.lat,
      property: ["phh2o", "clay", "sand", "soc"],
      depth: "0-5cm",
      value: "mean",
    },
    paramsSerializer: params => {
      const search = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (Array.isArray(value)) {
          value.forEach(item => search.append(key, item));
        } else {
          search.append(key, value);
        }
      });
      return search.toString();
    },
    timeout: 20000,
  });

  const layers = response.data?.properties?.layers || [];
  const ph = readSoilValue(layers.find(layer => layer.name === "phh2o"));
  const clay = readSoilValue(layers.find(layer => layer.name === "clay"));
  const sand = readSoilValue(layers.find(layer => layer.name === "sand"));
  const soc = readSoilValue(layers.find(layer => layer.name === "soc"));

  return {
    location: resolved.label,
    coordinates: { lat: resolved.lat, lon: resolved.lon },
    summary: {
      ph,
      clay,
      sand,
      organicCarbon: soc,
      textureClass: deriveSoilTexture(clay ?? 0, sand ?? 0),
      fertilityRating: deriveFertilityRating(soc ?? 0),
    },
    raw: response.data,
  };
}

async function fetchMarketPrices() {
  const updatedAt = new Date().toISOString();
  const externalUrl = process.env.MARKET_PRICES_URL;

  if (externalUrl) {
    try {
      const response = await axios.get(externalUrl, { timeout: 12000 });
      if (Array.isArray(response.data)) {
        return {
          source: "configured-market-feed",
          updatedAt,
          prices: response.data,
        };
      }
      if (Array.isArray(response.data?.prices)) {
        return {
          source: response.data.source || "configured-market-feed",
          updatedAt: response.data.updatedAt || updatedAt,
          prices: response.data.prices,
        };
      }
    } catch (_error) {
      // Fall through to the weekly fallback table.
    }
  }

  return {
    source: "fallback-east-africa-weekly-table",
    updatedAt,
    prices: FALLBACK_MARKET_PRICES,
  };
}

function formatSystemPrompt({ language, location, weather, soil, prices }) {
  const lang = getLanguage(language);
  return [
    "You are SHAMBA ASSISTANT, a Siri-like voice-first agricultural chatbot for East African farmers.",
    `You MUST respond ONLY in ${LANGUAGE_CONFIG[lang].label}. Do NOT use any other language under any circumstances.`,
    "You are a farming-only assistant. If the question is not about agriculture, crops, soil, weather for farming, livestock, irrigation, fertilizers, pest control, or rural food markets, warmly explain that you are an agricultural assistant only.",
    "For crop recommendations, ALWAYS return exactly Top 3 crops ranked with these medal emojis: 🥇, 🥈, 🥉.",
    "For each ranked crop, explain the reasoning using: current weather at the farmer's location, soil type from SoilGrids, and live market prices.",
    "Maintain full conversation continuity across the provided session history.",
    "Keep spoken-style answers concise at the top, then give practical structured details suitable for screen display.",
    `Current location: ${location}`,
    `Current weather JSON: ${JSON.stringify(weather)}`,
    `Soil Analysis for ${location}: ${JSON.stringify(soil)}`,
    `Live market prices JSON: ${JSON.stringify(prices)}`,
  ].join("\n");
}

async function buildAssistantContext({ location, lat, lon }) {
  const weather = await fetchWeatherContext({ location, lat, lon });
  const soil = await fetchSoilContext({
    location: weather.location,
    lat: weather.coordinates.lat,
    lon: weather.coordinates.lon,
  });
  const prices = await fetchMarketPrices();
  return { weather, soil, prices };
}

function toAnthropicMessages(history, message) {
  return [
    ...history.map(item => ({
      role: item.role,
      content: [{ type: "text", text: item.content }],
    })),
    {
      role: "user",
      content: [{ type: "text", text: message }],
    },
  ];
}

router.get("/config", (_req, res) => {
  res.json({
    defaultLocation: DEFAULT_LOCATION,
    defaultLanguage: DEFAULT_LANGUAGE,
    phoneNumber: process.env.TWILIO_PHONE_NUMBER || "+254700000000",
    continuousListeningDefault: false,
    suggestions: UI_SUGGESTIONS,
    twilioWebhookIncomingPath: "/voice/incoming",
    twilioWebhookRespondPath: "/voice/respond",
  });
});

router.get("/weather", async (req, res) => {
  try {
    const weather = await fetchWeatherContext({
      location: req.query.location || DEFAULT_LOCATION,
      lat: req.query.lat ? Number(req.query.lat) : undefined,
      lon: req.query.lon ? Number(req.query.lon) : undefined,
    });
    res.json(weather);
  } catch (error) {
    res.status(500).json({ error: error.message || "Failed to fetch weather." });
  }
});

router.get("/soil", async (req, res) => {
  try {
    const soil = await fetchSoilContext({
      location: req.query.location || DEFAULT_LOCATION,
      lat: req.query.lat ? Number(req.query.lat) : undefined,
      lon: req.query.lon ? Number(req.query.lon) : undefined,
    });
    res.json(soil);
  } catch (error) {
    res.status(500).json({ error: error.message || "Failed to fetch soil data." });
  }
});

router.get("/prices", async (_req, res) => {
  try {
    res.json(await fetchMarketPrices());
  } catch (error) {
    res.status(500).json({ error: error.message || "Failed to fetch prices." });
  }
});

router.post("/chat", async (req, res) => {
  try {
    const {
      message,
      sessionId = "default",
      language = DEFAULT_LANGUAGE,
      location = DEFAULT_LOCATION,
      lat,
      lon,
      reset = false,
    } = req.body || {};

    const trimmedMessage = String(message || "").trim();
    if (!trimmedMessage) {
      return res.status(400).json({ error: "Message is required." });
    }

    const lang = getLanguage(language);
    const store = getSessionStore(req);
    const session = getSession(store, sessionId);

    if (reset) {
      session.history = [];
    }

    session.language = lang;

    if (!isAgriculturalQuery(trimmedMessage)) {
      return res.json({
        reply: LANGUAGE_CONFIG[lang].onlyAg,
        language: lang,
        location: session.location,
        intent: detectIntent(trimmedMessage),
      });
    }

    const context = await buildAssistantContext({
      location,
      lat: typeof lat === "number" ? lat : Number(lat),
      lon: typeof lon === "number" ? lon : Number(lon),
    });

    session.location = context.weather.location;
    session.context = context;

    const payload = {
      model: ANTHROPIC_MODEL,
      max_tokens: 1200,
      system: formatSystemPrompt({
        language: lang,
        location: context.weather.location,
        weather: context.weather,
        soil: context.soil,
        prices: context.prices,
      }),
      messages: toAnthropicMessages(session.history, trimmedMessage),
    };

    const data = await anthropicRequest(payload);
    const reply = data.content?.map(item => item.text || "").join("\n").trim() || LANGUAGE_CONFIG[lang].onlyAg;

    session.history.push({ role: "user", content: trimmedMessage });
    session.history.push({ role: "assistant", content: reply });
    res.json({
      reply,
      language: lang,
      intent: detectIntent(trimmedMessage),
      location: context.weather.location,
      weather: context.weather,
      soil: context.soil,
      prices: context.prices,
      locationNotice: LANGUAGE_CONFIG[lang].locationUpdated(context.weather.location),
    });
  } catch (error) {
    const status = error.response?.status || 500;
    const detail = error.response?.data || error.message || "Chat request failed.";
    res.status(status).json({
      error: typeof detail === "string" ? detail : JSON.stringify(detail),
    });
  }
});

module.exports = router;
module.exports.helpers = {
  DEFAULT_LOCATION,
  DEFAULT_LANGUAGE,
  LANGUAGE_CONFIG,
  buildAssistantContext,
  formatSystemPrompt,
  anthropicRequest,
  isAgriculturalQuery,
  getLanguage,
};
