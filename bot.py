"""QR Buddy Telegram bot. Stores scan history in memory only; images are transient."""
import io
import asyncio
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
        "start": "ðŸ‘‹ Welcome to QR Buddy!\n\nðŸ“· Send a QR image or screenshot to scan it. I can detect multiple codes.\nâœ¨ Send text or a link and Iâ€™ll create a QR image.\n\nImages are processed temporarily. Recent results stay in memory only and may disappear when the service restarts.",
        "menu": "ðŸ“· Scan QR", "create": "âœ¨ Create QR", "history": "ðŸ•˜ History", "settings": "âš™ï¸ Settings",
        "choose": "Send me a QR image to scan, or send text/link to create a QR.", "none": "No QR code found. Try a clearer image.",
        "found": "ðŸ”Ž Found {n} QR code(s):", "text": "Text", "link": "Link", "caution": "âš ï¸ This link has unusual features ({why}). Check the full domain before opening. This check is only a heuristic.",
        "okay": "No obvious warning found, but this does not prove the site is safe.", "clear": "Recent scan history cleared.", "empty": "No recent scans.", "history": "ðŸ•˜ Your recent scans (kept in memory only):\n", "lang": "Language set to English.", "help": "Send an image to scan, or send plain text/a link to generate a QR. Commands: /start /lang /history /clear /help",
    },
    "km": {
        "start": "ðŸ‘‹ ážŸáž¼áž˜ážŸáŸ’ážœáž¶áž‚áž˜áž“áŸáž˜áž€áž€áž¶áž“áŸ‹ QR Buddy!\n\nðŸ“· áž•áŸ’áž‰áž¾ážšáž¼áž” QR áž¬ Screenshot ážŠáž¾áž˜áŸ’áž”áž¸ážŸáŸ’áž€áŸáž“áŸ” áž¢áž¶áž…ážšáž€ QR áž…áŸ’ážšáž¾áž“áž€áŸ’áž“áž»áž„ážšáž¼áž”ážáŸ‚áž˜áž½áž™áŸ”\nâœ¨ áž•áŸ’áž‰áž¾áž¢ážáŸ’ážáž”áž‘ áž¬ážáŸ†ážŽ ážŠáž¾áž˜áŸ’áž”áž¸áž”áž„áŸ’áž€áž¾ážážšáž¼áž” QRáŸ”\n\nážšáž¼áž”áž—áž¶áž–ážŠáŸ†ážŽáž¾ážšáž€áž¶ážšáž”ážŽáŸ’ážáŸ„áŸ‡áž¢áž¶ážŸáž“áŸ’áž“áŸ” áž›áž‘áŸ’áž’áž•áž›ážáŸ’áž˜áž¸áŸ—ážšáž€áŸ’ážŸáž¶áž‘áž»áž€ážáŸ‚áž€áŸ’áž“áž»áž„ memory áž áž¾áž™áž¢áž¶áž…áž”áž¶ážáŸ‹áž–áŸáž› service restartáŸ”",
        "menu": "ðŸ“· ážŸáŸ’áž€áŸáž“ QR", "create": "âœ¨ áž”áž„áŸ’áž€áž¾áž QR", "history": "ðŸ•˜ áž”áŸ’ážšážœážáŸ’ážáž·", "settings": "âš™ï¸ áž€áž¶ážšáž€áŸ†ážŽážáŸ‹",
        "choose": "áž•áŸ’áž‰áž¾ážšáž¼áž” QR ážŠáž¾áž˜áŸ’áž”áž¸ážŸáŸ’áž€áŸáž“ áž¬áž•áŸ’áž‰áž¾áž¢ážáŸ’ážáž”áž‘/ážáŸ†ážŽ ážŠáž¾áž˜áŸ’áž”áž¸áž”áž„áŸ’áž€áž¾áž QRáŸ”", "none": "ážšáž€áž˜áž·áž“ážƒáž¾áž‰ QR áž‘áŸáŸ” ážŸáž¶áž€áž›áŸ’áž”áž„ážšáž¼áž”ážŠáŸ‚áž›áž…áŸ’áž”áž¶ážŸáŸ‹áž‡áž¶áž„áž“áŸáŸ‡áŸ”",
        "found": "ðŸ”Ž ážšáž€ážƒáž¾áž‰ QR áž…áŸ†áž“áž½áž“ {n}áŸ–", "text": "áž¢ážáŸ’ážáž”áž‘", "link": "ážáŸ†ážŽ", "caution": "âš ï¸ ážáŸ†ážŽáž“áŸáŸ‡áž˜áž¶áž“áž›áž€áŸ’ážážŽáŸˆáž˜áž·áž“áž’áž˜áŸ’áž˜ážáž¶ ({why})áŸ” ážŸáž¼áž˜áž–áž·áž“áž·ážáŸ’áž™ domain áž–áŸáž‰áž˜áž»áž“áž”áž¾áž€áŸ” áž€áž¶ážšážáŸ’ážšáž½ážáž–áž·áž“áž·ážáŸ’áž™áž“áŸáŸ‡áž‚áŸ’ážšáž¶áž“áŸ‹ážáŸ‚áž‡áž¶áž€áž¶ážšáž”áŸ‰áž¶áž“áŸ‹ážŸáŸ’áž˜áž¶áž“áŸ”",
        "okay": "áž˜áž·áž“ážƒáž¾áž‰ážŸáž‰áŸ’áž‰áž¶áž–áŸ’ážšáž˜áž¶áž“áž…áŸ’áž”áž¶ážŸáŸ‹áž‘áŸ áž”áŸ‰áž»áž“áŸ’ážáŸ‚áž˜áž·áž“áž¢áž¶áž…áž’áž¶áž“áž¶ážáž¶áž‚áŸáž áž‘áŸ†áž–áŸážšáž˜áž¶áž“ážŸáž»ážœážáŸ’ážáž·áž—áž¶áž–áž‘áŸáŸ”", "clear": "áž”áž¶áž“áž›áž»áž”áž”áŸ’ážšážœážáŸ’ážáž·ážŸáŸ’áž€áŸáž“ážáŸ’áž˜áž¸áŸ—áŸ”", "empty": "áž˜áž·áž“áž‘áž¶áž“áŸ‹áž˜áž¶áž“áž”áŸ’ážšážœážáŸ’ážáž·ážŸáŸ’áž€áŸáž“áž‘áŸáŸ”", "history": "ðŸ•˜ áž”áŸ’ážšážœážáŸ’ážáž·ážŸáŸ’áž€áŸáž“ážáŸ’áž˜áž¸áŸ— (ážšáž€áŸ’ážŸáž¶áž‘áž»áž€áž€áŸ’áž“áž»áž„ memory áž”áŸ‰áž»ážŽáŸ’ážŽáŸ„áŸ‡)áŸ–\n", "lang": "áž”áž¶áž“áž€áŸ†ážŽážáŸ‹áž—áž¶ážŸáž¶ážáŸ’áž˜áŸ‚ážšáŸ”", "help": "áž•áŸ’áž‰áž¾ážšáž¼áž”ážŠáž¾áž˜áŸ’áž”áž¸ážŸáŸ’áž€áŸáž“ áž¬áž•áŸ’áž‰áž¾áž¢ážáŸ’ážáž”áž‘/ážáŸ†ážŽážŠáž¾áž˜áŸ’áž”áž¸áž”áž„áŸ’áž€áž¾áž QRáŸ” áž–áž¶áž€áŸ’áž™áž”áž‰áŸ’áž‡áž¶áŸ– /start /lang /history /clear /help",
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
    msg=await update.message.reply_text("â³ Scanningâ€¦")
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
            out.append(f"\n{i}. {'ðŸ”— '+tr(uid,'link') if is_link else 'ðŸ“ '+tr(uid,'text')}\n{value}")
            RECENT[uid].appendleft(value)
            if is_link:
                reasons=suspicious(value)
                out.append("\n"+(tr(uid,"caution").format(why=", ".join(reasons)) if reasons else tr(uid,"okay")))
        await msg.edit_text("".join(out), reply_markup=keyboard(uid), disable_web_page_preview=True)
    except Exception as exc:
        log.exception("Image scan failed")
        await msg.edit_text("âš ï¸ Could not scan this image. Try a JPG or PNG with a clear QR code.")

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; text=update.message.text.strip()
    buttons={tr(uid,"menu"),tr(uid,"create"),tr(uid,"history"),tr(uid,"settings")}
    if text in buttons:
        if text==tr(uid,"history"): return await history(update,context)
        return await choose(update,context)
    try: await update.message.reply_photo(photo=make_qr(text), caption="âœ¨ QR code Â· " + text[:800])
    except Exception:
        log.exception("QR generation failed")
        await update.message.reply_text("âš ï¸ Could not create that QR. Try shorter text.")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/health", "/"):
            body=b'{"status":"ok","service":"qr-buddy"}'
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        else: self.send_error(404)
    def log_message(self,*args): pass

def serve_health(): HTTPServer(("0.0.0.0",PORT),HealthHandler).serve_forever()

async def run_bot():
    """Explicit asyncio lifecycle works on modern Python versions too."""
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(CommandHandler("lang",setlang)); app.add_handler(CommandHandler("clear",clear)); app.add_handler(CommandHandler("history",history))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE,photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_message))
    await app.initialize()
    if app.updater is None:
        raise RuntimeError("Telegram updater is unavailable")
    await app.updater.start_polling(drop_pending_updates=True)
    await app.start()
    log.info("Telegram polling started")
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

def main():
    threading.Thread(target=serve_health,daemon=True).start()
    log.info("Starting QR Buddy bot and health server on port %s",PORT)
    asyncio.run(run_bot())

if __name__=="__main__": main()