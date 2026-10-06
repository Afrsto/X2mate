#!/usr/bin/env node
/**
 * Writes frontend/config.js at build time.
 * Prefer api-url.txt (committed / updated by local API tool); else X2MATE_API_URL env.
 */
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const filePath = path.join(root, "api-url.txt");
let api = "";
try {
  if (fs.existsSync(filePath)) {
    api = fs.readFileSync(filePath, "utf8").trim().split(/\r?\n/)[0].trim();
  }
} catch (_) {
  /* ignore */
}
if (!api) {
  api = (process.env.X2MATE_API_URL || "").trim();
}
api = api.replace(/\/$/, "");

const out = path.join(root, "config.js");
const body = `// Generated at build time (api-url.txt or X2MATE_API_URL)
window.__API_BASE__ = ${JSON.stringify(api)};
if (window.APP) {
  window.APP.apiBase = window.__API_BASE__ || window.APP.apiBase || "";
}
`;
fs.writeFileSync(out, body, "utf8");
console.log(
  api
    ? `inject-config: API base = ${api}`
    : "inject-config: no api-url.txt / X2MATE_API_URL — frontend will show backend not configured"
);
