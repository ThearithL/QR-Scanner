"""QR Buddy Telegram bot. Stores scan history in memory only; images are transient."""
import io
import logging
import os
import re
import threading
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import cv2
import numpy as np
import qrcode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("qr_buddy")
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MINI_APP_URL = os.getenv("MINI_APP_URL", "")
PORT = int(os.getenv("PORT", "10000"))
RECENT = defaultdict(lambda: deque(maxlen=20))
LANG = defaultdict(lambda: "en")

TEXT = {
    "en": {
        "start": "👋 Welcome to QR Buddy!\n\n📷 Send a QR image or screenshot to scan it. I can detect multiple codes.\n✨ Send text or a link and I’ll create a QR image.\n\nImages are processed temporarily. Recent results stay in memory only and may disappear when the service restarts.",
        "menu": "📷 Scan QR", "create": "✨ Create QR", "history": "🕘 History", "settings": "⚙️ Settings",
        "choose": "Send me a QR image to scan, or send text/link to create a QR.", "none": "No QR code found. Try a clearer image.",
        "found": "🔎 Found {n} QR code(s):", "text": "Text", "link": "Link", "caution": "⚠️ This link has unusual features ({why}). Check the full domain before opening. This check is only a heuristic.",
        "okay": "No obvious warning found, but this does not prove the site is safe.", "clear": "Recent scan history cleared.", "empty": "No recent scans.", "history": "🕘 Your recent scans (kept in memory only):\n", "lang": "Language set to English.", "help": "Send an image to scan, or send plain text/a link to generate a QR. Commands: /start /lang /history /clear /help",
    },
    "km": {
        "start": "👋 សូមស្វាគមន៍មកកាន់ QR Buddy!\n\n📷 ផ្ញើរូប QR ឬ Screenshot ដើម្បីស្កេន។ អាចរក QR ច្រើនក្នុងរូបតែមួយ។\n✨ ផ្ញើអត្ថបទ ឬតំណ ដើម្បីបង្កើតរូប QR។\n\nរូបភាពដំណើរការបណ្តោះអាសន្ន។ លទ្ធផលថ្មីៗរក្សាទុកតែក្នុង memory ហើយអាចបាត់ពេល service restart។",
        "menu": "📷 ស្កេន QR", "create": "✨ បង្កើត QR", "history": "🕘 ប្រវត្តិ", "settings": "⚙️ ការកំណត់",
        "choose": "ផ្ញើរូប QR ដើម្បីស្កេន ឬផ្ញើអត្ថបទ/តំណ ដើម្បីបង្កើត QR។", "none": "រកមិនឃើញ QR ទេ។ សាកល្បងរូបដែលច្បាស់ជាងនេះ។",
        "found": "🔎 រកឃើញ QR ចំនួន {n}៖", "text": "អត្ថបទ", "link": "តំណ", "caution": "⚠️ តំណនេះមានលក្ខណៈមិនធម្មតា ({why})។ សូមពិនិត្យ domain ពេញមុនបើក។ ការត្រួតពិនិត្យនេះគ្រាន់តែជាការប៉ាន់ស្មាន។",
        "okay": "មិនឃើញសញ្ញាព្រមានច្បាស់ទេ ប៉ុន្តែមិនអាចធានាថាគេហទំព័រមានសុវត្ថិភាពទេ។", "clear": "បានលុបប្រវត្តិស្កេនថ្មីៗ។", "empty": "មិនទាន់មានប្រវត្តិស្កេនទេ។", "history": "🕘 ប្រវត្តិស្កេនថ្មីៗ (រក្សាទុកក្នុង memory ប៉ុណ្ណោះ)៖\n", "lang": "បានកំណត់ភាសាខ្មែរ។", "help": "ផ្ញើរូបដើម្បីស្កេន ឬផ្ញើអត្ថបទ/តំណដើម្បីបង្កើត QR។ ពាក្យបញ្ជា៖ /start /lang /history /clear /help",
    },
}

def tr(uid, key):
    return TEXT[LANG[uid]][key]

def suspicious(value):
    try:
        u = urlparse(value)
        reasons = []
        if u.scheme not in ("http", "https"): reasons.append("unusual scheme")
        if u.username or u.password: reasons.append("embedded login")
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", u.hostname or "") or ":" in (u.hostname or ""): reasons.append("IP address")
        if any(part.startswith("xn--") for part in (u.hostname or "").split(".")): reasons.append("encoded domain")
        if (u.hostname or "").lower() in {"bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly"}: reasons.append("shortened URL")
        if not u.hostname or len(u.hostname) > 70: reasons.append("unusual domain")
        return reasons
    except Exception:
        return ["invalid link"]

def decode_image(data):
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None: return []
    detector = cv2.QRCodeDetector()
    try:
        ok, values, points, _ = detector.detectAndDecodeMulti(image)
        if ok: return [x for x in values if x]
    except Exception: pass
    value, _, _ = detector.detectAndDecode(image)
    return [value] if value else []

def make_qr(value):
    img = qrcode.make(value)
    buf = io.BytesIO(); buf.name = "qr-buddy.png"; img.save(buf, format="PNG"); buf.seek(0)
    return buf

def keyboard(uid):
    buttons = [[KeyboardButton(tr(uid, "menu")), KeyboardButton(tr(uid, "create"))],
               [KeyboardButton(tr(uid, "history")), KeyboardButton(tr(uid, "settings"))]]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def mini_button():
    if MINI_APP_URL.startswith("https://"):
        return InlineKeyboardMarkup([[InlineKeyboardButton("Open QR Buddy Mini App", web_app=WebAppInfo(url=MINI_APP_URL))]])
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    await update.message.reply_text(tr(uid,"start"), reply_markup=keyboard(uid))
    if MINI_APP_URL.startswith("https://"):
        await update.message.reply_text("Open the QR mini app:", reply_markup=mini_button())

async def choose(update, context):
    await update.message.reply_text(tr(update.effective_user.id,"choose"), reply_markup=keyboard(update.effective_user.id))

async def setlang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; LANG[uid]="km" if LANG[uid]=="en" else "en"
    await update.message.reply_text(tr(uid,"lang"), reply_markup=keyboard(uid))

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    RECENT[update.effective_user.id].clear()
    await update.message.reply_text(tr(update.effective_user.id,"clear"))

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; values=list(RECENT[uid])
    if not values: return await update.message.reply_text(tr(uid,"empty"))
    body=tr(uid,"history")+"\n".join(f"{i+1}. {x[:220]}" for i,x in enumerate(values))
    await update.message.reply_text(body)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(tr(update.effective_user.id,"help"))

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    msg=await update.message.reply_text("⏳ Scanning…")
    try:
        attachment=update.message.effective_attachment
        tgfile=await (attachment[-1] if isinstance(attachment,(list,tuple)) else attachment).get_file()
        data=bytes(await tgfile.download_as_bytearray())
        found=decode_image(data)
        del data
        if not found:
            await msg.edit_text(tr(uid,"none")); return
        out=[tr(uid,"found").format(n=len(found))]
        for i,value in enumerate(found,1):
            is_link=value.lower().startswith(("http://","https://"))
            out.append(f"\n{i}. {'🔗 '+tr(uid,'link') if is_link else '📝 '+tr(uid,'text')}\n{value}")
            RECENT[uid].appendleft(value)
            if is_link:
                reasons=suspicious(value)
                out.append("\n"+(tr(uid,"caution").format(why=", ".join(reasons)) if reasons else tr(uid,"okay")))
        await msg.edit_text("".join(out), reply_markup=keyboard(uid), disable_web_page_preview=True)
    except Exception as exc:
        log.exception("Image scan failed")
        await msg.edit_text("⚠️ Could not scan this image. Try a JPG or PNG with a clear QR code.")

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; text=update.message.text.strip()
    buttons={tr(uid,"menu"),tr(uid,"create"),tr(uid,"history"),tr(uid,"settings")}
    if text in buttons:
        if text==tr(uid,"history"): return await history(update,context)
        return await choose(update,context)
    try: await update.message.reply_photo(photo=make_qr(text), caption="✨ QR code · " + text[:800])
    except Exception:
        log.exception("QR generation failed")
        await update.message.reply_text("⚠️ Could not create that QR. Try shorter text.")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/health", "/"):
            body=b'{"status":"ok","service":"qr-buddy"}'
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        else: self.send_error(404)
    def log_message(self,*args): pass

def serve_health(): HTTPServer(("0.0.0.0",PORT),HealthHandler).serve_forever()

def main():
    threading.Thread(target=serve_health,daemon=True).start()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(CommandHandler("lang",setlang)); app.add_handler(CommandHandler("clear",clear)); app.add_handler(CommandHandler("history",history))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE,photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_message))
    log.info("Starting QR Buddy bot and health server on port %s",PORT)
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
