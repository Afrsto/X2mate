# X2mate

YouTube → **M4A** / **MP4** web downloader.

| Part | Role |
|------|------|
| [`frontend/`](frontend/) | Static UI on **Vercel** (https://x2mate.vercel.app) |
| [`backend/`](backend/) | Flask + yt-dlp API (Docker + ffmpeg) |

**Live frontend:** https://x2mate.vercel.app  
**Live API:** https://x2mate-api-production-bcfe.up.railway.app

## Frontend (Vercel)

Root directory: `frontend`. Build injects the API URL from env:

```text
X2MATE_API_URL=https://x2mate-api-production-bcfe.up.railway.app
```

```powershell
cd frontend
npx vercel --prod --scope x2-salah
```

## Backend

Docker image with ffmpeg — see [`backend/Dockerfile`](backend/Dockerfile) and [`render.yaml`](render.yaml) for a Render Blueprint deploy.

> **Render note:** Creating a new Render Web Service currently requires a payment card on the account (`dashboard.render.com/billing`). Until then the API runs on Railway at the URL above.

### YouTube cookies (Railway)

If YouTube returns a bot check on the server IP, set a Railway secret:

- `YOUTUBE_COOKIES` — full Netscape `cookies.txt` from a logged-in browser (extension export), **or**
- `YOUTUBE_COOKIES_B64` — same file, base64-encoded

The backend writes this to a temp file on boot and passes it to yt-dlp. Refresh cookies periodically if downloads start failing again.

### Local

```powershell
cd backend
pip install -r requirements.txt
python server.py
```

## Contacts

- Telegram: https://t.me/X2_616
- Discord user: https://discord.com/users/994817247061225633
- Discord server: https://discord.gg/btRCeujadA

## Disclaimer

Download only content you have the right to access. Respect YouTube’s Terms of Service and copyright law.
