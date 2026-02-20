"""
🎵 Music Downloader Bot
========================
Qo'shiq nomi yozilsa → 10 ta natija ro'yxati → raqam tanlansa → MP3

O'rnatish:
    pip install pyTelegramBotAPI yt-dlp python-dotenv static-ffmpeg

.env fayli:
    BOT_TOKEN=your_token_here

Ishga tushirish:
    python music_bot.py
"""

import os
import re
import sys
import logging
import threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# 🔧  FFMPEG AVTOMATIK SOZLASH
# ─────────────────────────────────────────────
def ensure_ffmpeg() -> str:
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        import shutil
        ffmpeg_bin = shutil.which("ffmpeg")
        print("✅ FFmpeg tayyor!")
        return str(Path(ffmpeg_bin).parent) if ffmpeg_bin else ""
    except ImportError:
        print("❌ static-ffmpeg o'rnatilmagan: pip install static-ffmpeg")
        sys.exit(1)
    except Exception as e:
        print(f"❌ FFmpeg xatosi: {e}")
        sys.exit(1)

print("⏳ FFmpeg tekshirilmoqda…")
FFMPEG_DIR = ensure_ffmpeg()

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

# ─────────────────────────────────────────────
# ⚙️  SOZLAMALAR
# ─────────────────────────────────────────────
BOT_TOKEN    = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
MAX_SIZE_MB  = 50
AUDIO_FORMAT = "mp3"
RESULTS_PER_PAGE = 10   # Har sahifada nechta natija

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# { chat_id: { "results": [...], "page": 0, "query": "..." } }
user_data: dict = {}


# ─────────────────────────────────────────────
# 🔧  YORDAMCHI FUNKSIYALAR
# ─────────────────────────────────────────────

def format_duration(seconds) -> str:
    if not seconds:
        return "?"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def search_tracks(query: str, max_results: int = 20) -> list:
    """YouTube dan qo'shiqlarni qidiradi (20 ta — sahifalash uchun)."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": True,   # tez qidiruv
    }
    if FFMPEG_DIR:
        opts["ffmpeg_location"] = FFMPEG_DIR
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"ytsearch{max_results}:{query}", download=False
            )
            return info.get("entries", []) or []
    except Exception as e:
        logger.error(f"Qidiruv xatosi: {e}")
        return []


def download_audio(url: str, filename: str) -> Path | None:
    """YouTube dan mp3 yuklab oladi."""
    safe = re.sub(r'[\\/*?:"<>|]', "_", filename)
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(DOWNLOAD_DIR / f"{safe}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": AUDIO_FORMAT,
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if FFMPEG_DIR:
        opts["ffmpeg_location"] = FFMPEG_DIR
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        for ext in [AUDIO_FORMAT, "m4a", "webm", "opus"]:
            p = DOWNLOAD_DIR / f"{safe}.{ext}"
            if p.exists():
                return p
        files = sorted(DOWNLOAD_DIR.glob("*"), key=os.path.getmtime, reverse=True)
        return files[0] if files else None
    except Exception as e:
        logger.error(f"Yuklash xatosi: {e}")
        return None


def send_audio_file(chat_id: int, path: Path, title: str, artist: str):
    size_mb = path.stat().st_size / 1_048_576
    if size_mb > MAX_SIZE_MB:
        bot.send_message(chat_id, f"❌ Fayl juda katta ({size_mb:.1f} MB).")
        path.unlink(missing_ok=True)
        return
    with open(path, "rb") as f:
        bot.send_audio(
            chat_id, f,
            title=title,
            performer=artist,
            caption="🎵 Mana qo'shig'ingiz!",
        )
    path.unlink(missing_ok=True)


# ─────────────────────────────────────────────
# 🎨  NATIJALAR XABARI VA TUGMALARI
# ─────────────────────────────────────────────

def build_results_message(results: list, page: int) -> str:
    """Sahifadagi natijalar ro'yxatini matnga aylantiradi."""
    start = page * RESULTS_PER_PAGE
    page_results = results[start: start + RESULTS_PER_PAGE]

    lines = []
    for i, item in enumerate(page_results, 1):
        title    = item.get("title", "Noma'lum")
        duration = format_duration(item.get("duration"))
        # Uzun nomlarni qisqartirish
        if len(title) > 45:
            title = title[:43] + "…"
        lines.append(f"*{i}.* {title} `{duration}`")

    total_pages = (len(results) - 1) // RESULTS_PER_PAGE + 1
    header = f"🎵 *Qidiruv natijalari* — sahifa {page + 1}/{total_pages}\n\n"
    return header + "\n".join(lines)


def build_results_keyboard(results: list, page: int) -> InlineKeyboardMarkup:
    """Raqamli tugmalar + navigatsiya."""
    start        = page * RESULTS_PER_PAGE
    page_results = results[start: start + RESULTS_PER_PAGE]
    total_pages  = (len(results) - 1) // RESULTS_PER_PAGE + 1

    kb = InlineKeyboardMarkup(row_width=5)

    # 1-5 raqamlar
    row1 = [
        InlineKeyboardButton(str(i + 1), callback_data=f"pick:{page}:{i}")
        for i in range(min(5, len(page_results)))
    ]
    # 6-10 raqamlar
    row2 = [
        InlineKeyboardButton(str(i + 1), callback_data=f"pick:{page}:{i}")
        for i in range(5, min(10, len(page_results)))
    ]

    if row1:
        kb.row(*row1)
    if row2:
        kb.row(*row2)

    # Navigatsiya: ◀️ ❌ ▶️
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"page:{page - 1}"))
    else:
        nav.append(InlineKeyboardButton("◀️", callback_data="noop"))

    nav.append(InlineKeyboardButton("❌", callback_data="cancel"))

    if (page + 1) < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"page:{page + 1}"))
    else:
        nav.append(InlineKeyboardButton("▶️", callback_data="noop"))

    kb.row(*nav)
    return kb


# ─────────────────────────────────────────────
# 🤖  BUYRUQLAR
# ─────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    name = message.from_user.first_name or "Do'stim"
    text = (
        f"Salom, *{name}*! 👋\n\n"
        "🎵 *Music Bot* ga xush kelibsiz!\n\n"
        "Qo'shiq nomini yozing va yuklab oling,\n"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    text = (
        "🎵 *Qanday foydalanish:*\n\n"
        "1️⃣ Qo'shiq nomini yozing\n"
        "2️⃣ 10 ta natija ro'yxati chiqadi\n"
        "3️⃣ Kerakli raqamni bosing\n"
        "4️⃣ MP3 fayl keladi!\n\n"
        "◀️ ▶️ — sahifalar o'rtasida o'tish\n"
        "❌ — bekor qilish"
    )
    bot.send_message(message.chat.id, text)


# ─────────────────────────────────────────────
# 📝  MATN → QIDIRUV
# ─────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
def handle_text(message):
    query   = message.text.strip()
    chat_id = message.chat.id

    if len(query) < 2:
        bot.send_message(chat_id, "⚠️ Kamida 2 ta harf kiriting.")
        return

    msg = bot.send_message(chat_id, "🔍 Qidirilmoqda…")

    def search_thread():
        results = search_tracks(query, max_results=20)

        if not results:
            bot.edit_message_text(
                "❌ Hech narsa topilmadi.\n\nBoshqacha nom kiriting.",
                chat_id, msg.message_id
            )
            return

        # Saqlash
        user_data[chat_id] = {
            "results": results,
            "page":    0,
            "query":   query,
        }

        text = build_results_message(results, page=0)
        kb   = build_results_keyboard(results, page=0)

        bot.edit_message_text(
            text, chat_id, msg.message_id,
            reply_markup=kb,
            parse_mode="Markdown"
        )

    threading.Thread(target=search_thread).start()


# ─────────────────────────────────────────────
# 🔘  INLINE TUGMALAR
# ─────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    data    = call.data

    # ── Hech narsa qilmaslik (disabled tugma) ──
    if data == "noop":
        bot.answer_callback_query(call.id)
        return

    # ── Bekor qilish ────────────────────────────
    if data == "cancel":
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        bot.answer_callback_query(call.id)
        user_data.pop(chat_id, None)
        return

    # ── Sahifa o'tish ───────────────────────────
    if data.startswith("page:"):
        state = user_data.get(chat_id)
        if not state:
            bot.answer_callback_query(call.id, "❌ Qayta qidiring.")
            return

        new_page = int(data.split(":")[1])
        state["page"] = new_page

        text = build_results_message(state["results"], new_page)
        kb   = build_results_keyboard(state["results"], new_page)

        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(
                text, chat_id, call.message.message_id,
                reply_markup=kb, parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # ── Qo'shiq tanlash va yuklash ───────────────
    if data.startswith("pick:"):
        state = user_data.get(chat_id)
        if not state:
            bot.answer_callback_query(call.id, "❌ Qayta qidiring.")
            return

        _, page_str, idx_str = data.split(":")
        page = int(page_str)
        idx  = int(idx_str)

        start  = page * RESULTS_PER_PAGE
        item   = state["results"][start + idx]

        title    = item.get("title", "Noma'lum")
        uploader = item.get("uploader") or item.get("channel", "—")
        url      = item.get("url") or item.get("webpage_url", "")

        if not url:
            # extract_flat=True da URL to'liq bo'lmasligi mumkin
            url = f"https://www.youtube.com/watch?v={item.get('id', '')}"

        bot.answer_callback_query(call.id, f"⏳ {title[:30]}…")

        try:
            bot.edit_message_text(
                f"⏳ *Yuklanmoqda…*\n\n🎵 {title}\n👤 {uploader}",
                chat_id, call.message.message_id,
                parse_mode="Markdown"
            )
        except Exception:
            pass

        def dl_thread():
            path = download_audio(url, f"{uploader} - {title}")
            if not path or not path.exists():
                bot.send_message(chat_id, "❌ Yuklashda xatolik. Qayta urinib ko'ring.")
                return
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            send_audio_file(chat_id, path, title, uploader)
            user_data.pop(chat_id, None)

        threading.Thread(target=dl_thread).start()


# ─────────────────────────────────────────────
# 🚀  ISHGA TUSHIRISH
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ BOT_TOKEN kiritilmagan! .env faylini tekshiring.")
        sys.exit(1)

    print("✅ Bot ishlamoqda…  Ctrl+C bilan to'xtatish mumkin.\n")
    bot.infinity_polling(timeout=30, long_polling_timeout=20)