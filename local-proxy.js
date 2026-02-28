#!/usr/bin/env node
// Local proxy: transparent forwarder to api.anthropic.com with OAuth auth.
// Injects Authorization + anthropic-beta headers; streams the response back.
// Run with: node local-proxy.js  (or: make proxy)

const { createServer } = require("http");
const { request: httpsRequest } = require("https");
const fs = require("fs");
const path = require("path");

// Minimal .env loader — no dotenv dependency
const envFile = path.join(__dirname, ".env");
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, "utf8").split("\n")) {
    const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*$/);
    if (m) process.env[m[1]] ??= m[2].replace(/^['"]|['"]$/g, "");
  }
}

const PORT = 7337;
const MODEL = "claude-sonnet-4-6";
const MAX_RPM = 60;

const token = process.env.CLAUDE_CODE_OAUTH_TOKEN;
if (!token) {
  console.error("Error: CLAUDE_CODE_OAUTH_TOKEN not set. Copy .env.example → .env and fill it in.");
  process.exit(1);
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, anthropic-version, anthropic-beta",
};

let reqCount = 0;
setInterval(() => { reqCount = 0; }, 60_000);

function forwardErrorResponse(apiRes, res) {
  let body = "";
  apiRes.on("data", (chunk) => { body += chunk; });
  apiRes.on("end", () => {
    console.error("API error:", body);
    res.writeHead(apiRes.statusCode, CORS_HEADERS);
    res.end(body);
  });
}

createServer((req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS_HEADERS);
    res.end();
    return;
  }

  if (req.method !== "POST" || req.url !== "/claude") {
    res.writeHead(404);
    res.end();
    return;
  }

  if (++reqCount > MAX_RPM) {
    console.warn(`Rate limit hit (${MAX_RPM} req/min)`);
    res.writeHead(429, CORS_HEADERS);
    res.end();
    return;
  }

  let body = "";
  req.on("data", (chunk) => { body += chunk; });
  req.on("end", () => {
    let msg;
    try {
      msg = JSON.parse(body);
    } catch {
      res.writeHead(400, CORS_HEADERS);
      res.end("Bad JSON");
      return;
    }

    if (!msg.model?.startsWith("claude-")) msg.model = MODEL;
    const payload = JSON.stringify(msg);

    console.log(`→ ${payload.length}b  model=${msg.model}`);

    const apiReq = httpsRequest({
      hostname: "api.anthropic.com",
      path: "/v1/messages",
      method: "POST",
      headers: {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
        "authorization": `Bearer ${token}`,
        "content-length": Buffer.byteLength(payload),
      },
    }, apiRes => {
      console.log(`← ${apiRes.statusCode}`);
      if (apiRes.statusCode !== 200) {
        return forwardErrorResponse(apiRes, res);
      }
      res.writeHead(200, {
        ...CORS_HEADERS,
        "content-type": apiRes.headers["content-type"] ?? "text/event-stream",
      });
      apiRes.pipe(res);
    });

    apiReq.on("error", (e) => {
      console.error("Request failed:", e.message);
      if (!res.headersSent) res.writeHead(500, CORS_HEADERS);
      res.end();
    });

    apiReq.end(payload);
  });
}).listen(PORT, "127.0.0.1", () => {
  console.log(`\n  Claude proxy → http://127.0.0.1:${PORT}`);
  console.log(`  Token: ${token.slice(0, 8)}…${token.slice(-4)}\n`);
});
