const express = require("express");
const path = require("path");
const cors = require("cors");
const helmet = require("helmet");
const rateLimit = require("express-rate-limit");
require("dotenv").config();

const apiRoutes = require("./routes/api");
const voiceRoutes = require("./routes/voice");

const app = express();
const port = Number(process.env.PORT || 3000);

app.locals.sessions = new Map();

app.use(
  helmet({
    contentSecurityPolicy: false,
    crossOriginEmbedderPolicy: false,
  })
);
app.use(
  cors({
    origin: true,
    credentials: true,
  })
);
app.use(express.json({ limit: "2mb" }));
app.use(express.urlencoded({ extended: true }));

const chatLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 30,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    error: "Too many chat requests. Please try again in a moment.",
  },
});

app.use("/api/chat", chatLimiter);
app.use("/api", apiRoutes);
app.use("/voice", voiceRoutes);
app.use(express.static(path.join(__dirname, "public")));

app.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    service: "shamba-assistant",
    timestamp: new Date().toISOString(),
  });
});

app.get("*", (_req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

app.listen(port, () => {
  console.log(`SHAMBA ASSISTANT running on port ${port}`);
});
