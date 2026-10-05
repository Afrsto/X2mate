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

## Deploy on Render

1. Open [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**
2. Connect `Afrsto/X2mate` and use the root [`render.yaml`](../render.yaml)
3. Or **New Web Service** → Docker → Root Directory `backend`
4. After deploy, copy the service URL (e.g. `https://x2mate-api.onrender.com`)
5. Set Vercel env `X2MATE_API_URL` to that URL and redeploy the frontend

CORS is open for `/api/*` so the Vercel origin can call this API.

**Note:** Free Render services sleep after inactivity; the first request may take ~30–60s while waking up.
