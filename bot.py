"""QR Code Scanner Telegram bot. Stores scan history in memory only; images are transient."""
import io
import asyncio
import logging
import os
import re
import threading
from pathlib import Path
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import cv2
import numpy as np
import zxingcpp
import qrcode
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, MenuButtonWebApp, ReplyKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("qr_buddy")
# httpx logs full Telegram API request URLs at INFO, which can expose the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MINI_APP_URL = os.getenv("MINI_APP_URL", "")
PORT = int(os.getenv("PORT", "10000"))
RECENT = defaultdict(lambda: deque(maxlen=20))
LANG = defaultdict(lambda: "en")
PENDING = defaultdict(str)

TEXT = {
    "en": {
        "start": "\U0001f44b Welcome to QR Code Scanner!\n\n\U0001f4f7 Send a QR image or screenshot to scan it. I can detect multiple codes.\n\u2728 Send text or a link and I\u2019ll create a QR image.\n\nImages are processed temporarily. Recent results stay in memory only and may disappear when the service restarts.",
        "menu": "\U0001f4f7 Scan QR", "create": "\u2728 Create QR", "history": "\U0001f558 History", "settings": "\u2699\ufe0f Settings", "language": "\U0001f310 Change language",
        "convert": "\U0001f504 Convert link / QR",
        "settings_msg": "\U0001f310 Tap Change language below or send /lang to switch between English and Khmer.",
        "convert_msg": "\U0001f517 Link to QR: send me a link and I will return a QR image.\n\U0001f4f7 QR to link: send me a QR photo or screenshot and I will read its contents.",
        "choose": "Send me a QR image to scan, or send text/link to create a QR.", "scan_prompt": "Send a QR photo or image file and I will scan it.", "create_prompt": "Send the text or link you want to turn into a QR code. Use /cancel to stop.", "cancelled": "Cancelled. Send a QR image or text/link whenever you are ready.", "privacy": "Privacy: uploaded images are processed temporarily for scanning and are not archived by this bot. Recent decoded results are kept in memory only and may disappear when Render restarts. The Mini App scans images locally in your browser.", "none": "No QR code found. Try a clearer image.",
        "found": "\U0001f50e Found {n} QR code(s):", "text": "Text", "link": "Link", "caution": "\u26a0\ufe0f This link has unusual features ({why}). Check the full domain before opening. This check is only a heuristic.",
        "okay": "No obvious warning found, but this does not prove the site is safe.", "clear": "Recent scan history cleared.", "empty": "No recent scans.", "history": "\U0001f558 Your recent scans (kept in memory only):\n", "lang": "Language set to English.", "help": "Send an image to scan, or send plain text/a link to generate a QR. Commands: /start /scan /createqr /miniapp /history /clear /lang /privacy /cancel /help",
        "too_large": "This image is too large to scan here. Send a smaller image, or use the Mini App to scan it on your device.",
        "no_detail": "Tip: send the original QR image as a File/Document to preserve its quality. Telegram compresses photos.",
        "size_help": "Current QR image size: {size}px. Set it with /size 256, /size 512, /size 1024, or /size 2048. Example: /size 1024",
        "size_set": "QR image size set to {size}px. This setting is kept while the bot is running.",
    },
    "km": {
        "start": "\U0001f44b \u179f\u17bc\u1798\u179f\u17d2\u179c\u17b6\u1782\u1798\u1793\u17cd\u1798\u1780\u1780\u17b6\u1793\u17cb QR Code Scanner!\n\n\U0001f4f7 \u1795\u17d2\u1789\u17be\u179a\u17bc\u1794 QR \u17ac Screenshot \u178a\u17be\u1798\u17d2\u1794\u17b8\u179f\u17d2\u1780\u17c1\u1793\u17d4 \u17a2\u17b6\u1785\u179a\u1780 QR \u1785\u17d2\u179a\u17be\u1793\u1780\u17d2\u1793\u17bb\u1784\u179a\u17bc\u1794\u178f\u17c2\u1798\u17bd\u1799\u17d4\n\u2728 \u1795\u17d2\u1789\u17be\u17a2\u178f\u17d2\u1790\u1794\u1791 \u17ac\u178f\u17c6\u178e \u178a\u17be\u1798\u17d2\u1794\u17b8\u1794\u1784\u17d2\u1780\u17be\u178f\u179a\u17bc\u1794 QR\u17d4\n\n\u179a\u17bc\u1794\u1797\u17b6\u1796\u178a\u17c6\u178e\u17be\u179a\u1780\u17b6\u179a\u1794\u178e\u17d2\u178f\u17c4\u17c7\u17a2\u17b6\u179f\u1793\u17d2\u1793\u17d4 \u179b\u1791\u17d2\u1792\u1795\u179b\u1790\u17d2\u1798\u17b8\u17d7\u179a\u1780\u17d2\u179f\u17b6\u1791\u17bb\u1780\u178f\u17c2\u1780\u17d2\u1793\u17bb\u1784 memory \u17a0\u17be\u1799\u17a2\u17b6\u1785\u1794\u17b6\u178f\u17cb\u1796\u17c1\u179b service restart\u17d4",
        "menu": "\U0001f4f7 \u179f\u17d2\u1780\u17c1\u1793 QR", "create": "\u2728 \u1794\u1784\u17d2\u1780\u17be\u178f QR", "history": "\U0001f558 \u1794\u17d2\u179a\u179c\u178f\u17d2\u178f\u17b7", "settings": "\u2699\ufe0f \u1780\u17b6\u179a\u1780\u17c6\u178e\u178f\u17cb", "language": "\U0001f310 \u1794\u17d2\u178f\u17bc\u179a\u1797\u17b6\u179f\u17b6",
        "convert": "\U0001f504 \u1794\u17d2\u178f\u17bc\u179a\u178f\u17c6\u178e / QR",
        "settings_msg": "\U0001f310 \u1785\u17bb\u1785 \xab\u1794\u17d2\u178f\u17bc\u179a\u1797\u17b6\u179f\u17b6\xbb \u1781\u17b6\u1784\u1780\u17d2\u179a\u17c4\u1798 \u17ac\u1795\u17d2\u1789\u17be /lang \u178a\u17be\u1798\u17d2\u1794\u17b8\u1794\u17d2\u178f\u17bc\u179a\u179a\u179c\u17b6\u1784\u1797\u17b6\u179f\u17b6\u1781\u17d2\u1798\u17c2\u179a \u1793\u17b7\u1784\u17a2\u1784\u17cb\u1782\u17d2\u179b\u17c1\u179f\u17d4",
        "convert_msg": "\U0001f517 \u178f\u17c6\u178e \u1791\u17c5 QR: \u1795\u17d2\u1789\u17be\u178f\u17c6\u178e\u1798\u1780\u1794\u17bc\u178f \u178a\u17be\u1798\u17d2\u1794\u17b8\u1791\u1791\u17bd\u179b\u1794\u17b6\u1793\u179a\u17bc\u1794 QR\u17d4\n\U0001f4f7 QR \u1791\u17c5\u178f\u17c6\u178e: \u1795\u17d2\u1789\u17be\u179a\u17bc\u1794 QR \u17ac screenshot \u178a\u17be\u1798\u17d2\u1794\u17b8\u17b1\u17d2\u1799\u1794\u17bc\u178f\u17a2\u17b6\u1793\u1796\u17d0\u178f\u17cc\u1798\u17b6\u1793\u179a\u1794\u179f\u17cb\u179c\u17b6\u17d4",
        "choose": "\u1795\u17d2\u1789\u17be\u179a\u17bc\u1794 QR \u178a\u17be\u1798\u17d2\u1794\u17b8\u179f\u17d2\u1780\u17c1\u1793 \u17ac\u1795\u17d2\u1789\u17be\u17a2\u178f\u17d2\u1790\u1794\u1791/\u178f\u17c6\u178e \u178a\u17be\u1798\u17d2\u1794\u17b8\u1794\u1784\u17d2\u1780\u17be\u178f QR\u17d4", "scan_prompt": "\u1795\u17d2\u1789\u17be\u179a\u17bc\u1794 QR \u17ac\u17af\u1780\u179f\u17b6\u179a\u179a\u17bc\u1794\u1797\u17b6\u1796 \u1790\u17be\u1794\u17bc\u178f\u1793\u17b9\u1784\u179f\u17d2\u1780\u17c1\u1793\u179c\u17b6\u17d4", "create_prompt": "\u1795\u17d2\u1789\u17be\u17a2\u178f\u17d2\u1790\u1794\u1791 \u17ac\u178f\u17c6\u178e \u178a\u17be\u1798\u17d2\u1794\u17b8\u1794\u1784\u17d2\u1780\u17be\u178f QR Code\u17d4 \u1794\u17d2\u179a\u17be /cancel \u178a\u17be\u1798\u17d2\u1794\u17b8\u1794\u17c4\u17c7\u1794\u1784\u17cb\u17d4", "cancelled": "\u1794\u17b6\u1793\u1794\u1789\u17d2\u1788\u1794\u17cb\u17a0\u17be\u1799\u17d4 \u17a2\u17d2\u1793\u1780\u17a2\u17b6\u1785\u1795\u17d2\u1789\u17be\u179a\u17bc\u1794 QR \u17ac\u17a2\u178f\u17d2\u1790\u1794\u1791/\u178f\u17c6\u178e\u1794\u17b6\u1793\u17d4", "privacy": "\u17af\u1780\u1787\u1793\u1797\u17b6\u1796\u17d6 \u179a\u17bc\u1794\u1797\u17b6\u1796\u1795\u17d2\u1789\u17be\u1798\u1780\u178f\u17d2\u179a\u17bc\u179c\u1794\u17d2\u179a\u1796\u17b9\u178f\u17d2\u178f\u1794\u178e\u17d2\u178f\u17c4\u17c7\u17a2\u17b6\u179f\u1793\u17d2\u1793\u179f\u1798\u17d2\u179a\u17b6\u1794\u17cb\u179f\u17d2\u1780\u17c1\u1793 \u17a0\u17be\u1799\u1798\u17b7\u1793\u179a\u1780\u17d2\u179f\u17b6\u1791\u17bb\u1780\u1791\u17c1\u17d4 \u1794\u17d2\u179a\u179c\u178f\u17d2\u178f\u17b7\u179b\u1791\u17d2\u1792\u1795\u179b\u1790\u17d2\u1798\u17b8\u17d7\u179a\u1780\u17d2\u179f\u17b6\u1791\u17bb\u1780\u178f\u17c2\u1780\u17d2\u1793\u17bb\u1784 memory \u17a0\u17be\u1799\u17a2\u17b6\u1785\u1794\u17b6\u178f\u17cb\u1796\u17c1\u179b Render restart\u17d4 Mini App \u179f\u17d2\u1780\u17c1\u1793\u179a\u17bc\u1794\u1793\u17c5\u179b\u17be browser \u179a\u1794\u179f\u17cb\u17a2\u17d2\u1793\u1780\u17d4", "none": "\u179a\u1780\u1798\u17b7\u1793\u1783\u17be\u1789 QR \u1791\u17c1\u17d4 \u179f\u17b6\u1780\u179b\u17d2\u1794\u1784\u179a\u17bc\u1794\u178a\u17c2\u179b\u1785\u17d2\u1794\u17b6\u179f\u17cb\u1787\u17b6\u1784\u1793\u17c1\u17c7\u17d4",
        "found": "\U0001f50e \u179a\u1780\u1783\u17be\u1789 QR \u1785\u17c6\u1793\u17bd\u1793 {n}\u17d6", "text": "\u17a2\u178f\u17d2\u1790\u1794\u1791", "link": "\u178f\u17c6\u178e", "caution": "\u26a0\ufe0f \u178f\u17c6\u178e\u1793\u17c1\u17c7\u1798\u17b6\u1793\u179b\u1780\u17d2\u1781\u178e\u17c8\u1798\u17b7\u1793\u1792\u1798\u17d2\u1798\u178f\u17b6 ({why})\u17d4 \u179f\u17bc\u1798\u1796\u17b7\u1793\u17b7\u178f\u17d2\u1799 domain \u1796\u17c1\u1789\u1798\u17bb\u1793\u1794\u17be\u1780\u17d4 \u1780\u17b6\u179a\u178f\u17d2\u179a\u17bd\u178f\u1796\u17b7\u1793\u17b7\u178f\u17d2\u1799\u1793\u17c1\u17c7\u1782\u17d2\u179a\u17b6\u1793\u17cb\u178f\u17c2\u1787\u17b6\u1780\u17b6\u179a\u1794\u17c9\u17b6\u1793\u17cb\u179f\u17d2\u1798\u17b6\u1793\u17d4",
        "okay": "\u1798\u17b7\u1793\u1783\u17be\u1789\u179f\u1789\u17d2\u1789\u17b6\u1796\u17d2\u179a\u1798\u17b6\u1793\u1785\u17d2\u1794\u17b6\u179f\u17cb\u1791\u17c1 \u1794\u17c9\u17bb\u1793\u17d2\u178f\u17c2\u1798\u17b7\u1793\u17a2\u17b6\u1785\u1792\u17b6\u1793\u17b6\u1790\u17b6\u1782\u17c1\u17a0\u1791\u17c6\u1796\u17d0\u179a\u1798\u17b6\u1793\u179f\u17bb\u179c\u178f\u17d2\u1790\u17b7\u1797\u17b6\u1796\u1791\u17c1\u17d4", "clear": "\u1794\u17b6\u1793\u179b\u17bb\u1794\u1794\u17d2\u179a\u179c\u178f\u17d2\u178f\u17b7\u179f\u17d2\u1780\u17c1\u1793\u1790\u17d2\u1798\u17b8\u17d7\u17d4", "empty": "\u1798\u17b7\u1793\u1791\u17b6\u1793\u17cb\u1798\u17b6\u1793\u1794\u17d2\u179a\u179c\u178f\u17d2\u178f\u17b7\u179f\u17d2\u1780\u17c1\u1793\u1791\u17c1\u17d4", "history": "\U0001f558 \u1794\u17d2\u179a\u179c\u178f\u17d2\u178f\u17b7\u179f\u17d2\u1780\u17c1\u1793\u1790\u17d2\u1798\u17b8\u17d7 (\u179a\u1780\u17d2\u179f\u17b6\u1791\u17bb\u1780\u1780\u17d2\u1793\u17bb\u1784 memory \u1794\u17c9\u17bb\u178e\u17d2\u178e\u17c4\u17c7)\u17d6\n", "lang": "\u1794\u17b6\u1793\u1780\u17c6\u178e\u178f\u17cb\u1797\u17b6\u179f\u17b6\u1781\u17d2\u1798\u17c2\u179a\u17d4", "help": "\u1795\u17d2\u1789\u17be\u179a\u17bc\u1794\u178a\u17be\u1798\u17d2\u1794\u17b8\u179f\u17d2\u1780\u17c1\u1793 \u17ac\u1795\u17d2\u1789\u17be\u17a2\u178f\u17d2\u1790\u1794\u1791/\u178f\u17c6\u178e\u178a\u17be\u1798\u17d2\u1794\u17b8\u1794\u1784\u17d2\u1780\u17be\u178f QR\u17d4 \u1796\u17b6\u1780\u17d2\u1799\u1794\u1789\u17d2\u1787\u17b6\u17d6 /start /scan /createqr /miniapp /history /clear /lang /privacy /cancel /help",
        "too_large": "\u179a\u17bc\u1794\u1792\u17c6\u1796\u17c1\u1780\u179f\u1798\u17d2\u179a\u17b6\u1794\u17cb\u179f\u17d2\u1780\u17c1\u1793\u1793\u17c5\u1791\u17b8\u1793\u17c1\u17c7\u17d4 \u179f\u17bc\u1798\u1795\u17d2\u1789\u17be\u179a\u17bc\u1794\u178f\u17bc\u1785\u1787\u17b6\u1784\u1793\u17c1\u17c7 \u17ac\u1794\u17be\u1780 Mini App \u178a\u17be\u1798\u17d2\u1794\u17b8\u179f\u17d2\u1780\u17c1\u1793\u1793\u17c5\u179b\u17be\u17a7\u1794\u1780\u179a\u178e\u17cd\u179a\u1794\u179f\u17cb\u17a2\u17d2\u1793\u1780\u17d4",
        "no_detail": "\u1787\u17bd\u1799\u17b1\u17d2\u1799\u179f\u17d2\u1780\u17c1\u1793\u1787\u17b6\u1780\u17cb\u179b\u17b6\u1780\u17d4 \u179f\u17bc\u1798\u1795\u17d2\u1789\u17be\u179a\u17bc\u1794 QR \u1787\u17b6 File/Document \u178a\u17be\u1798\u17d2\u1794\u17b8\u179a\u1780\u17d2\u179f\u17b6\u1782\u17bb\u178e\u1797\u17b6\u1796\u178a\u17be\u1798\u17d4 Telegram \u1794\u1784\u17d2\u179a\u17bd\u1789\u1782\u17bb\u178e\u1797\u17b6\u1796\u179a\u17bc\u1794\u1796\u17c1\u179b\u1795\u17d2\u1789\u17be\u1787\u17b6 Photo\u17d4",
        "size_help": "\u1791\u17c6\u17a0\u17c6\u179a\u17bc\u1794 QR \u1794\u1785\u17d2\u1785\u17bb\u1794\u17d2\u1794\u1793\u17d2\u1793\u17d6 {size}px\u17d4 \u1780\u17c6\u178e\u178f\u17cb\u1787\u17b6\u1798\u17bd\u1799 /size 256, /size 512, /size 1024 \u17ac /size 2048\u17d4 \u17a7\u1791\u17b6\u17a0\u179a\u178e\u17cd\u17d6 /size 1024",
        "size_set": "\u1794\u17b6\u1793\u1780\u17c6\u178e\u178f\u17cb\u1791\u17c6\u17a0\u17c6\u179a\u17bc\u1794 QR \u1791\u17c5 {size}px\u17d4 \u1780\u17b6\u179a\u1780\u17c6\u178e\u178f\u17cb\u1793\u17c1\u17c7\u179a\u1780\u17d2\u179f\u17b6\u1791\u17bb\u1780\u178f\u17c2\u1780\u17d2\u1793\u17bb\u1784 memory \u178f\u17d2\u179a\u17b9\u1798\u1796\u17c1\u179b bot \u1780\u17c6\u1796\u17bb\u1784\u178a\u17c6\u178e\u17be\u179a\u1780\u17b6\u179a\u1794\u17c9\u17bb\u178e\u17d2\u178e\u17c4\u17c7\u17d4",
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
    """Decode QR symbols using ZXing first and enhanced OpenCV fallbacks.

    ZXing handles stylized/color/inverted and multi-symbol QR images better than
    OpenCV alone. Inputs are capped to avoid excessive memory on giant uploads.
    """
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return []
    h, w = image.shape[:2]
    scale = min(1.0, 2400 / max(h, w))
    if scale < 1:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    decoded = []
    seen = set()

    def add(values):
        for value in values:
            value = (value or "").strip()
            if value and value not in seen:
                seen.add(value)
                decoded.append(value)

    # Prefer a dedicated QR decoder. Also try luminance and inverted grayscale
    # because colorful logos and dark-background QR designs can confuse binarizing.
    try:
        add(r.text for r in zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode))
    except Exception:
        log.exception("ZXing QR decode failed")
    if decoded:
        return decoded

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants = [image, gray, cv2.equalizeHist(gray), cv2.bitwise_not(gray)]
    # Improve low contrast, grayscale and tiny QR images.
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    variants.extend([clahe, cv2.bitwise_not(clahe)])
    for src in (gray, clahe):
        _, otsu = cv2.threshold(src, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.extend([otsu, cv2.bitwise_not(otsu)])
        adaptive = cv2.adaptiveThreshold(src, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                         cv2.THRESH_BINARY, 31, 5)
        variants.extend([adaptive, cv2.bitwise_not(adaptive)])
    if max(gray.shape[:2]) < 1800:
        variants.extend(cv2.resize(v, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                        for v in list(variants))

    detector = cv2.QRCodeDetector()
    for candidate in variants:
        try:
            results = zxingcpp.read_barcodes(candidate, formats=zxingcpp.BarcodeFormat.QRCode)
            add(r.text for r in results)
            if decoded:
                return decoded
        except Exception:
            pass
        try:
            ok, values, _, _ = detector.detectAndDecodeMulti(candidate)
            if ok:
                add(values)
        except Exception:
            pass
        if decoded:
            return decoded
        try:
            value, _, _ = detector.detectAndDecode(candidate)
            add([value])
        except Exception:
            pass
        if decoded:
            return decoded
    return decoded

def make_qr(value, size=1024):
    # Dark teal on white keeps a branded look while preserving strong contrast.
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=max(1, min(2048, int(size)) // 45),
        border=4,
    )
    qr.add_data(value)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#123C46", back_color="#FFFFFF")
    buf = io.BytesIO(); buf.name = "qr-code-scanner.png"; img.save(buf, format="PNG"); buf.seek(0)
    return buf

def keyboard(uid):
    buttons = [[KeyboardButton(tr(uid, "menu")), KeyboardButton(tr(uid, "create"))],
               [KeyboardButton(tr(uid, "history")), KeyboardButton(tr(uid, "settings"))],
               [KeyboardButton(tr(uid, "convert")), KeyboardButton(tr(uid, "language"))]]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def mini_button():
    if MINI_APP_URL.startswith("https://"):
        return InlineKeyboardMarkup([[InlineKeyboardButton("Open QR Code Scanner", web_app=WebAppInfo(url=MINI_APP_URL))]])
    return None

async def configure_user_menu(bot, uid):
    """Make this user's Telegram chat menu open the Mini App directly."""
    if not MINI_APP_URL.startswith("https://"):
        log.warning("MINI_APP_URL is missing or is not HTTPS; Telegram menu remains the command list")
        return False
    try:
        await bot.set_chat_menu_button(
            chat_id=uid,
            menu_button=MenuButtonWebApp(
                text="QR Code Scanner",
                web_app=WebAppInfo(url=MINI_APP_URL),
            ),
        )
        return True
    except Exception:
        log.exception("Could not set the QR Code Scanner menu button for chat %s", uid)
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    await configure_user_menu(context.bot, uid)
    await update.message.reply_text(tr(uid,"start"), reply_markup=keyboard(uid))
    if MINI_APP_URL.startswith("https://"):
        await update.message.reply_text("Open the QR mini app:", reply_markup=mini_button())

async def choose(update, context):
    uid=update.effective_user.id
    await update.message.reply_text(tr(uid,"choose"), reply_markup=keyboard(uid))

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

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    PENDING[uid] = "scan"
    await update.message.reply_text(tr(uid, "scan_prompt"), reply_markup=keyboard(uid))

async def createqr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    PENDING[uid] = "create"
    await update.message.reply_text(tr(uid, "create_prompt"), reply_markup=keyboard(uid))

async def size_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    allowed = {256, 512, 1024, 2048}
    if context.args:
        try:
            size = int(context.args[0])
        except ValueError:
            size = 0
        if size not in allowed:
            return await update.message.reply_text(tr(uid, "size_help").format(size=context.user_data.get("qr_size", 1024)))
        context.user_data["qr_size"] = size
        return await update.message.reply_text(tr(uid, "size_set").format(size=size))
    await update.message.reply_text(tr(uid, "size_help").format(size=context.user_data.get("qr_size", 1024)))

async def miniapp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if MINI_APP_URL.startswith("https://"):
        await configure_user_menu(context.bot, update.effective_user.id)
        await update.message.reply_text("Open QR Code Scanner:", reply_markup=mini_button())
    else:
        await update.message.reply_text("Mini App is not configured yet. Set MINI_APP_URL in Render.")

async def privacy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(tr(update.effective_user.id, "privacy"))

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    PENDING.pop(update.effective_user.id, None)
    await update.message.reply_text(tr(update.effective_user.id, "cancelled"), reply_markup=keyboard(update.effective_user.id))

async def set_commands(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Open QR Code Scanner menu"),
        BotCommand("scan", "Scan a QR image"),
        BotCommand("createqr", "Create a QR from text or a link"),
        BotCommand("size", "Set QR image size: 256, 512, 1024, or 2048"),
        BotCommand("miniapp", "Open the QR Mini App"),
        BotCommand("history", "Show recent scans"),
        BotCommand("clear", "Clear recent scans"),
        BotCommand("lang", "Switch Khmer / English"),
        BotCommand("privacy", "See how images and history are handled"),
        BotCommand("cancel", "Cancel the current action"),
        BotCommand("help", "Show available commands"),
    ])
    # Replace Telegram's default "Menu" command-list button with a direct
    # Mini App launcher. Slash commands remain available to users.
    if MINI_APP_URL.startswith("https://"):
        await configure_user_menu(app.bot, None)

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    PENDING.pop(uid, None)
    msg=await update.message.reply_text("\u23f3 Scanning\u2026")
    try:
        attachment=update.message.effective_attachment
        tgfile=await (attachment[-1] if isinstance(attachment,(list,tuple)) else attachment).get_file()
        data=bytes(await tgfile.download_as_bytearray())
        if len(data) > 15 * 1024 * 1024:
            await msg.edit_text(tr(uid,"too_large"), reply_markup=keyboard(uid)); return
        # Keep CPU-heavy decoding off the Telegram polling event loop.
        found=await asyncio.to_thread(decode_image,data)
        del data
        if not found:
            await msg.edit_text(tr(uid,"none")+"\n\n"+tr(uid,"no_detail"), reply_markup=keyboard(uid)); return
        out=[tr(uid,"found").format(n=len(found))]
        for i,value in enumerate(found,1):
            is_link=value.lower().startswith(("http://","https://"))
            out.append(f"\n{i}. {'\U0001f517 '+tr(uid,'link') if is_link else '\U0001f4dd '+tr(uid,'text')}\n{value}")
            RECENT[uid].appendleft(value)
            if is_link:
                reasons=suspicious(value)
                out.append("\n"+(tr(uid,"caution").format(why=", ".join(reasons)) if reasons else tr(uid,"okay")))
        # Reply keyboards cannot be attached to editMessageText; send the
        # decoded result as a new message, where Telegram accepts the menu.
        await update.message.reply_text(
            "".join(out), reply_markup=keyboard(uid), disable_web_page_preview=True
        )
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as exc:
        log.exception("Image scan failed")
        await msg.edit_text("\u26a0\ufe0f Could not scan this image. Try a JPG or PNG with a clear QR code.")

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; text=update.message.text.strip()
    buttons={tr(uid,"menu"),tr(uid,"create"),tr(uid,"history"),tr(uid,"settings"),tr(uid,"language"),tr(uid,"convert")}
    if text in buttons:
        if text==tr(uid,"history"): return await history(update,context)
        if text==tr(uid,"language"): return await setlang(update,context)
        if text==tr(uid,"menu"): return await scan_cmd(update,context)
        if text==tr(uid,"create"): return await createqr_cmd(update,context)
        if text==tr(uid,"convert"):
            return await update.message.reply_text(tr(uid,"convert_msg"), reply_markup=keyboard(uid))
        if text==tr(uid,"settings"):
            return await update.message.reply_text(tr(uid,"settings_msg"), reply_markup=keyboard(uid))
        return await choose(update,context)
    PENDING.pop(uid, None)
    try: await update.message.reply_photo(photo=make_qr(text, context.user_data.get("qr_size", 1024)), caption="\u2728 QR code \xb7 " + text[:800])
    except Exception:
        log.exception("QR generation failed")
        await update.message.reply_text("\u26a0\ufe0f Could not create that QR. Try shorter text.")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body=b'{"status":"ok","service":"qr-buddy"}'
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        elif self.path in ("/", "/index.html"):
            try:
                body=(Path(__file__).resolve().parent / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                self.send_error(500, "Mini App file index.html is missing")
        else: self.send_error(404)
    def log_message(self,*args): pass

def serve_health(): HTTPServer(("0.0.0.0",PORT),HealthHandler).serve_forever()

async def run_bot():
    """Explicit asyncio lifecycle works on modern Python versions too."""
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(CommandHandler("lang",setlang)); app.add_handler(CommandHandler("clear",clear)); app.add_handler(CommandHandler("history",history))
    app.add_handler(CommandHandler("scan",scan_cmd)); app.add_handler(CommandHandler("createqr",createqr_cmd))
    app.add_handler(CommandHandler("size",size_cmd))
    app.add_handler(CommandHandler("miniapp",miniapp_cmd)); app.add_handler(CommandHandler("privacy",privacy_cmd)); app.add_handler(CommandHandler("cancel",cancel_cmd))
    app.add_handler(CommandHandler("about",help_cmd))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE,photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_message))
    await app.initialize()
    await set_commands(app)
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
    log.info("Starting QR Code Scanner bot and health server on port %s",PORT)
    asyncio.run(run_bot())

if __name__=="__main__": main()
