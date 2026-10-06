# QR Buddy — Telegram QR scanner + Mini App

A bilingual (Khmer/English) QR scanner and QR creator. The Mini App scans images locally in the browser. The Telegram bot scans image uploads transiently and can generate QR images from text or links.

## Features

- Scan QR codes from photos, screenshots, and image files; attempt multi-code detection with ZXing and enhanced OpenCV fallbacks for colorful, inverted, or logo-style codes.
- Use the Mini App quick menu to jump to Scan, Create, Convert, History, and language controls.
- Use the **Convert** option for either direction: turn a link into a QR image, or scan a QR image to read its link/text.
- Create QR images for any text or URL in the bot. The Mini App additionally builds URL, text, phone, Wi‑Fi, and location QR payloads.
- Heuristic warnings for suspicious-looking links. Link checks are not a security guarantee, and links are never opened automatically.
- Khmer/English UI, menu buttons, recent scan history, `/clear`, `/history`, `/lang`, and `/help`.
- The Mini App processes images in the browser. Scan history lives in that browser's local storage; bot history is in memory only and disappears when Render restarts or sleeps.
- No database, no image archive, and no bot token in source control.

## Run locally (Windows PowerShell)

1. Install Python 3.12 and Git if they are not installed.
2. In the project directory, run:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

3. Create a bot with Telegram's **@BotFather**, copy its token, then edit `.env` and set `TELEGRAM_BOT_TOKEN`.
4. Start the bot:

   ```powershell
   $env:TELEGRAM_BOT_TOKEN="YOUR_TOKEN"
   python bot.py
   ```

5. Open `index.html` in a browser to try the Mini App. Telegram's in-app Web App button requires a publicly reachable HTTPS URL.

## Deploy free on Render

This repo has a `render.yaml` Blueprint with two services:

1. Push this folder to a GitHub repository.
2. In Render, choose **New → Blueprint**, connect the repository, and deploy the services.
3. The Static Site should receive a public URL such as `https://qr-buddy-miniapp.onrender.com`. Copy it.
4. In the `qr-buddy-bot` service's Environment settings, set:
   - `TELEGRAM_BOT_TOKEN` — token from @BotFather (keep secret).
   - `MINI_APP_URL` — the Static Site HTTPS URL.
5. Save changes/redeploy, then open the bot and send `/start`.

The bot Web Service also serves the Mini App at its root URL (`https://<your-bot-service>.onrender.com/`) and keeps `/health` for Render's health check. You can set `MINI_APP_URL` to this same bot-service HTTPS URL, so the Mini App button opens the app instead of the JSON health response. The separate Static Site is optional; if you use it, set `MINI_APP_URL` to that site's HTTPS URL instead.

The mini app is a Render **Static Site**, so it does not use a sleeping web server. Render Free **Web Services** can spin down after 15 minutes without inbound requests, then need about a minute to start on the next request. A `/health` endpoint is included for service health checks, but health checks do not keep a Free service awake. Telegram bot polling is outbound traffic and does not count as inbound traffic to prevent spin-down. Therefore the bot may be temporarily unavailable after idle periods. Render does not provide an always-on bot on the Free web-service plan; to keep the bot continuously available, use a paid always-on service or a hosting provider with a suitable free always-on worker plan.

Free Render service filesystems are ephemeral. This project intentionally keeps no permanent server-side scan history or uploaded images. A service restart also clears bot's in-memory recent history.

## Telegram Mini App setup

- The Mini App URL must use HTTPS and be publicly accessible.
- The bot sends an inline **Open QR Buddy Mini App** button if `MINI_APP_URL` is set.
- The app also works as a normal website; Telegram WebApp APIs are optional enhancements.

## Commands

`/start` opens the menu · `/lang` toggles Khmer/English · `/history` shows recent bot scans · `/clear` clears that in-memory history · `/help` explains usage.

## Notes

Browser QR scanning and generation use jsQR and qrcode.js CDNs, so an internet connection is required for those libraries. Link checks use lightweight heuristics only. Do not treat them as antivirus or proof that a URL is safe.
