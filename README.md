# X2mate

YouTube → **M4A** / **MP4** web downloader.

| Part | Role |
|------|------|
| [`frontend/`](frontend/) | Static UI hosted on **Vercel** |
| [`backend/`](backend/) | Flask + yt-dlp API on **Render** (Docker + ffmpeg) |

**Live:** https://x2mate.vercel.app

## Frontend (Vercel)

Root directory: `frontend`. Build injects the API URL from env:

```text
X2MATE_API_URL=https://your-render-service.onrender.com
```

```powershell
cd frontend
npx vercel --prod --scope x2-salah
```

## Backend (Render)

See [`backend/README.md`](backend/README.md). Blueprint: [`render.yaml`](render.yaml).

## Contacts

- Telegram: https://t.me/X2_616
- Discord user: https://discord.com/users/994817247061225633
- Discord server: https://discord.gg/btRCeujadA

## Disclaimer

Download only content you have the right to access. Respect YouTube’s Terms of Service and copyright law.
