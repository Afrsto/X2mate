# X2mate

YouTube → **M4A** / **MP4** web downloader.

| Part | Role |
|------|------|
| [`frontend/`](frontend/) | Static UI hosted on **Vercel** |
| [`backend/`](backend/) | Flask + yt-dlp API (host separately — Railway / Render / VPS) |

## Frontend (Vercel)

```powershell
cd frontend
npx vercel --prod
```

Or connect this GitHub repo in the Vercel dashboard with **Root Directory** = `frontend` and team scope matching your account.

Without a backend URL, the UI loads but downloads/search show that the API is unreachable. Set the API in [`frontend/config.js`](frontend/config.js):

```js
window.__API_BASE__ = "https://your-backend.example.com";
```

## Backend

See [`backend/README.md`](backend/README.md).

## Contacts

- Telegram: https://t.me/X2_616
- Discord user: https://discord.com/users/994817247061225633
- Discord server: https://discord.gg/btRCeujadA

## Disclaimer

Download only content you have the right to access. Respect YouTube’s Terms of Service and copyright law.
