#!/usr/bin/env node
/**
 * Writes frontend/config.js from env X2MATE_API_URL at Vercel build time.
 * Example: X2MATE_API_URL=https://x2mate-api.onrender.com
 */
const fs = require("fs");
const path = require("path");

const api = (process.env.X2MATE_API_URL || "").trim().replace(/\/$/, "");
const out = path.join(__dirname, "..", "config.js");
const body = `// Generated at build time from X2MATE_API_URL
window.__API_BASE__ = ${JSON.stringify(api)};
if (window.APP) {
  window.APP.apiBase = window.__API_BASE__ || window.APP.apiBase || "";
}
`;
fs.writeFileSync(out, body, "utf8");
console.log(
  api
    ? `inject-config: API base = ${api}`
    : "inject-config: X2MATE_API_URL empty — frontend will show backend not configured"
);
