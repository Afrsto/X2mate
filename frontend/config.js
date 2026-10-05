// Optional runtime API base for Vercel. Override by editing this file or setting
// window.__API_BASE__ before load. Example: "https://your-backend.example.com"
window.__API_BASE__ = window.__API_BASE__ || "";
if (window.APP) {
  window.APP.apiBase = window.__API_BASE__ || window.APP.apiBase || "";
}
