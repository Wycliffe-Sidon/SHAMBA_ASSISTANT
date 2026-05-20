const express = require("express");
const twilio = require("twilio");

const { helpers } = require("./api");

const router = express.Router();

function getCallSession(store, callSid) {
  const key = `voice:${callSid || "default"}`;
  if (!store.has(key)) {
    store.set(key, {
      history: [],
      language: helpers.DEFAULT_LANGUAGE,
      location: helpers.DEFAULT_LOCATION,
      context: null,
    });
  }
  return store.get(key);
}

function getVoiceStyle(language) {
  if (language === "sw") {
    return { sayLanguage: "sw", localeLabel: "Kiswahili" };
  }
  if (language === "luo") {
    return { sayLanguage: "en-KE", localeLabel: "Luo-Dholuo" };
  }
  return { sayLanguage: "en-KE", localeLabel: "English" };
}

function buildGather(response, language, params = {}) {
  const style = getVoiceStyle(language);
  return response.gather({
    input: "speech",
    action: `/voice/respond?lang=${encodeURIComponent(language)}&location=${encodeURIComponent(params.location || helpers.DEFAULT_LOCATION)}`,
    method: "POST",
    language: style.sayLanguage,
    speechTimeout: "auto",
    timeout: 6,
  });
}

function buildPhonePrompt(language) {
  return helpers.LANGUAGE_CONFIG[language]?.prompt || helpers.LANGUAGE_CONFIG.en.prompt;
}

router.post("/incoming", async (req, res) => {
  const language = helpers.getLanguage(req.body.lang || req.query.lang || helpers.DEFAULT_LANGUAGE);
  const location = String(req.body.location || req.query.location || helpers.DEFAULT_LOCATION);
  const response = new twilio.twiml.VoiceResponse();
  response.say({ language: getVoiceStyle(language).sayLanguage }, helpers.LANGUAGE_CONFIG[language].greeting);
  const gather = buildGather(response, language, { location });
  gather.say({ language: getVoiceStyle(language).sayLanguage }, buildPhonePrompt(language));
  res.type("text/xml").send(response.toString());
});

router.post("/respond", async (req, res) => {
  const callSid = req.body.CallSid || "default";
  const spokenText = String(req.body.SpeechResult || "").trim();
  const language = helpers.getLanguage(req.body.lang || req.query.lang || helpers.DEFAULT_LANGUAGE);
  const location = String(req.body.location || req.query.location || helpers.DEFAULT_LOCATION);
  const style = getVoiceStyle(language);
  const session = getCallSession(req.app.locals.sessions, callSid);
  const response = new twilio.twiml.VoiceResponse();

  session.language = language;
  session.location = location;

  if (!spokenText) {
    const gather = buildGather(response, language, { location });
    gather.say({ language: style.sayLanguage }, helpers.LANGUAGE_CONFIG[language].prompt);
    return res.type("text/xml").send(response.toString());
  }

  if (!helpers.isAgriculturalQuery(spokenText)) {
    response.say({ language: style.sayLanguage }, helpers.LANGUAGE_CONFIG[language].onlyAg);
    const gather = buildGather(response, language, { location });
    gather.say({ language: style.sayLanguage }, helpers.LANGUAGE_CONFIG[language].prompt);
    return res.type("text/xml").send(response.toString());
  }

  try {
    const context = await helpers.buildAssistantContext({ location });
    session.location = context.weather.location;
    session.context = context;

    const payload = {
      model: "claude-sonnet-4-20250514",
      max_tokens: 700,
      system: helpers.formatSystemPrompt({
        language,
        location: context.weather.location,
        weather: context.weather,
        soil: context.soil,
        prices: context.prices,
      }),
      messages: [
        ...session.history.map(item => ({
          role: item.role,
          content: [{ type: "text", text: item.content }],
        })),
        {
          role: "user",
          content: [{ type: "text", text: spokenText }],
        },
      ],
    };

    const data = await helpers.anthropicRequest(payload);
    const reply = data.content?.map(item => item.text || "").join("\n").trim() || helpers.LANGUAGE_CONFIG[language].onlyAg;

    session.history.push({ role: "user", content: spokenText });
    session.history.push({ role: "assistant", content: reply });

    response.say({ language: style.sayLanguage }, reply);
    const gather = buildGather(response, language, { location: session.location });
    gather.say({ language: style.sayLanguage }, helpers.LANGUAGE_CONFIG[language].prompt);
    return res.type("text/xml").send(response.toString());
  } catch (_error) {
    response.say({ language: style.sayLanguage }, helpers.LANGUAGE_CONFIG[language].onlyAg);
    const gather = buildGather(response, language, { location });
    gather.say({ language: style.sayLanguage }, helpers.LANGUAGE_CONFIG[language].prompt);
    return res.type("text/xml").send(response.toString());
  }
});

module.exports = router;
