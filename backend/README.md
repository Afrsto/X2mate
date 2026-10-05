# X2mate backend

Always-on Flask API for the X2mate Vercel frontend (yt-dlp + ffmpeg).

## Requirements

- Python 3.9+
- ffmpeg on PATH

## Run locally

```powershell
pip install -r requirements.txt
python server.py
```

Listens on `http://0.0.0.0:8787` (or `$env:PORT`).

## Deploy

Host on Railway, Render, Fly.io, or any VPS. Then set the frontend API base:

1. Edit `frontend/config.js`: `window.__API_BASE__ = "https://your-backend.example.com";`
2. Redeploy the Vercel frontend

CORS is open for `/api/*` so the Vercel origin can call this API.
