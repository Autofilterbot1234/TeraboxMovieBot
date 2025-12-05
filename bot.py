#
# ----------------------------------------------------
# Developed by: Ctgmovies23
# Final Version: Advanced Auto Filter + Web Verification (Toggle System)
# Status: 100% Verified & Optimized + 6 Button Admin Panel
# ----------------------------------------------------
#

import os
import re
import time
import math
import asyncio
import logging
import secrets
import urllib.parse
from datetime import datetime, timezone, timedelta
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

# ------------------- লাইব্রেরি ইম্পোর্ট -------------------
import ujson  # Fast JSON
import aiohttp # For Async Web Requests (BS4 & TMDB)
from bs4 import BeautifulSoup 
from flask import Flask

# Pyrogram
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid

# Database & Search
from motor.motor_asyncio import AsyncIOMotorClient # Async DB
from pymongo import MongoClient, ASCENDING # Sync DB for indexing only
from fuzzywuzzy import process, fuzz # Fuzzy Logic
from marshmallow import Schema, fields, ValidationError # Schema Validation

# ------------------- কনফিগারেশন -------------------
API_ID = int(os.getenv("API_ID", "0")) 
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))

# Admin ID parsing
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/TGLinkBase")
TMDB_API_KEY = os.getenv("TMDB_API_KEY") 
START_PIC = os.getenv("START_PIC", "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg")
BROADCAST_PIC = os.getenv("BROADCAST_PIC", "https://telegra.ph/file/18659550b694b47000787.jpg")

# --- WEB & ADS CONFIGURATION ---
BASE_URL = os.getenv("BASE_URL", "http://localhost:8080") 

# Koyeb থেকে AD_CODE_HEAD এবং AD_CODE_BODY সেট করবেন
AD_CODE_HEAD = os.getenv("AD_CODE_HEAD", "") 
AD_CODE_BODY = os.getenv("AD_CODE_BODY", """
<div style="text-align: center; color: #ffaa00; margin: 10px;">
    <h3>⬇️ Download Link Generating... ⬇️</h3>
</div>
""") 

# অটো মেসেজ সেটিংস
AUTO_MSG_INTERVAL = 1200  
AUTO_MSG_DELETE_TIME = 300 

AUTO_MESSAGE_TEXT = """
**🔔 নিয়মিত আপডেট!**

🎬 নতুন নতুন মুভি পেতে আমাদের সাথেই থাকুন।
যে কোনো মুভি খুঁজতে মুভির নাম লিখে সার্চ করুন।

✅ জয়েন করুন: @TGLinkBase
"""

# লগিং সেটআপ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Client Setup
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- MongoDB Setup -------------------
try:
    motor_client = AsyncIOMotorClient(DATABASE_URL)
    db = motor_client["movie_bot"]

    movies_col = db["movies"]
    users_col = db["users"]
    groups_col = db["groups"]
    settings_col = db["settings"]
    requests_col = db["requests"]
    feedback_col = db["feedback"]
    verify_col = db["verification"] 

    # Sync Client (ইনডেক্স তৈরির জন্য)
    sync_client = MongoClient(DATABASE_URL)
    sync_db = sync_client["movie_bot"]
    sync_db.movies.create_index("message_id", unique=True, background=True)
    sync_db.movies.create_index([("title_clean", ASCENDING)], background=True)
    sync_db.movies.create_index("language", background=True)
    sync_db.movies.create_index([("views_count", ASCENDING)], background=True)
    
    # TTL Index (টোকেন ১ ঘন্টা পর অটো ডিলিট হবে)
    sync_db.verification.create_index("created_at", expireAfterSeconds=3600)
    print("✅ Database Indexes & TTL Created Successfully!")
except Exception as e:
    print(f"⚠️ Database Connection Error: {e}")

# Schema
class MovieSchema(Schema):
    message_id = fields.Int(required=True)
    title = fields.Str(required=True)
    title_clean = fields.Str(required=True)
    full_caption = fields.Str()
    year = fields.Int(allow_none=True)
    language = fields.Str(allow_none=True)
    views_count = fields.Int(load_default=0)
    thumbnail_id = fields.Str(allow_none=True)
    date = fields.DateTime()

movie_schema = MovieSchema()

async def init_settings():
    try:
        # Default Settings
        await settings_col.update_one({"key": "protect_forwarding"}, {"$setOnInsert": {"value": True}}, upsert=True)
        # ডিফল্টভাবে ভেরিফিকেশন অন থাকবে (True), আপনি অফ করতে চাইলে /verify off দিবেন
        await settings_col.update_one({"key": "verification_mode"}, {"$setOnInsert": {"value": True}}, upsert=True)
        await settings_col.update_one({"key": "global_notify"}, {"$setOnInsert": {"value": True}}, upsert=True)
    except Exception as e:
        logger.error(f"Settings Init Error: {e}")

# ------------------- Flask অ্যাপ (Website & Ads) -------------------
flask_app = Flask(__name__)

def get_verification_html(heading, timer_seconds, next_link, btn_text):
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Secure Link Verification</title>
        <style>
            body {{
                background-color: #121212;
                color: #e0e0e0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
                text-align: center;
                padding: 20px;
            }}
            .container {{
                background: #1e1e1e;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5);
                max-width: 100%;
                width: 400px;
                border: 1px solid #333;
            }}
            h2 {{ color: #00ff88; margin-bottom: 15px; font-size: 22px; }}
            p {{ font-size: 16px; margin-bottom: 20px; }}
            .timer-box {{
                font-size: 20px;
                font-weight: bold;
                color: #ffaa00;
                margin: 15px 0;
                padding: 12px;
                background: #2a2a2a;
                border-radius: 8px;
            }}
            .btn {{
                display: none;
                background: linear-gradient(135deg, #007bff, #0056b3);
                color: white;
                padding: 14px 28px;
                text-decoration: none;
                font-size: 18px;
                border-radius: 8px;
                font-weight: bold;
                transition: transform 0.2s;
                width: 100%;
                box-sizing: border-box;
                margin-top: 15px;
            }}
            .btn:hover {{ transform: scale(1.02); }}
            .ad-area {{
                margin: 20px 0;
                background: #252525;
                min-height: 250px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 8px;
                overflow: hidden;
            }}
            footer {{ margin-top: 20px; font-size: 12px; color: #777; }}
        </style>
        <!-- Adsterra Head Code -->
        {AD_CODE_HEAD}
    </head>
    <body>
        <div class="container">
            <h2>🛡️ Link Verification System</h2>
            <p>{heading}</p>
            
            <!-- Adsterra Body Banner -->
            <div class="ad-area">
                {AD_CODE_BODY}
            </div>

            <div class="timer-box">
                Please Wait: <span id="count">{timer_seconds}</span> seconds
            </div>
            
            <a id="actionBtn" href="{next_link}" class="btn">{btn_text}</a>
            
            <footer>
                Secured by MovieBot &bull; Fast & Safe
            </footer>
        </div>

        <script>
            var counter = {timer_seconds};
            var interval = setInterval(function() {{
                counter--;
                document.getElementById("count").innerHTML = counter;
                if (counter <= 0) {{
                    clearInterval(interval);
                    document.querySelector(".timer-box").style.display = "none";
                    document.getElementById("actionBtn").style.display = "block";
                }}
            }}, 1000);
        </script>
    </body>
    </html>
    """

@flask_app.route("/")
def home():
    return "Bot & Web Server is Running! 🚀"

@flask_app.route("/verify/<token>")
def verify_page_one(token):
    # টোকেন চেক
    data = sync_db.verification.find_one({"token": token})
    if not data:
        return "❌ Invalid Link! Please search again in Telegram."

    # পেজ ১: ১০ সেকেন্ড অপেক্ষা -> স্টেপ ২ লিংকে যাবে
    next_url = f"{BASE_URL}/verify/step2/{token}"
    
    return get_verification_html(
        heading="Step 1/2: Verifying your request...",
        timer_seconds=10,
        next_link=next_url,
        btn_text="Next Step 🚀"
    )

@flask_app.route("/verify/step2/<token>")
def verify_page_two(token):
    # ডাটাবেস আপডেট: স্টেপ ২ সম্পন্ন
    res = sync_db.verification.update_one({"token": token}, {"$set": {"step": 2}})
    if res.matched_count == 0:
        return "❌ Session Expired. Search again."

    # পেজ ২: ১০ সেকেন্ড অপেক্ষা -> টেলিগ্রামে ফিরবে
    bot_username = app.me.username if app.me else "TGLinkBaseBot" 
    final_link = f"https://t.me/{bot_username}?start=verified_{token}"

    return get_verification_html(
        heading="Step 2/2: Generating Download Link...",
        timer_seconds=10,
        next_link=final_link,
        btn_text="GET FILE NOW ✅"
    )

# Flask Server in Thread
def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask).start() 
thread_pool_executor = ThreadPoolExecutor(max_workers=5)

# ------------------- হেল্পার ফাংশন -------------------

STOP_WORDS = [
    "movie", "movies", "film", "films", "cinema", "show", "series", "season", "episode", 
    "full", "link", "links", "download", "watch", "online", "free", "all", "part", "url",
    "hindi", "bengali", "bangla", "english", "tamil", "telugu", "kannada", "malayalam", 
    "korean", "japanese", "chinese", "spanish", "french", "dubbed", "dual", "audio", 
    "sub", "esub", "subbed", "org", "original",
    "hd", "fhd", "4k", "8k", "1080p", "720p", "480p", "360p", "240p", 
    "cam", "hdcam", "rip", "web", "webrip", "hdrip", "bluray", "dvd", "dvdscr", 
    "hevc", "x264", "x265", "10bit", "60fps", "hdr", "amzn", "nf", "hulu", "mp4", "mkv",
    "drive", "mega", "gd", "gdrive", "direct", "zone", "hub", "flix", "moviez", "movi",
    "dao", "daw", "den", "din", "lagbe", "chai", "koi", "ase", "nai", "plz", "pls", "please",
    "karo", "koro", "ta", "dorkar", "urgent", "fast", "server", "site", "telegram", "channel",
    "s01", "s02", "e01", "e02", "complete", "pack", "collection"
]

def clean_text(text):
    text = text.lower()
    text = re.sub(r'(?<!\d)(19|20)\d{2}(?!\d)', '', text) 
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    words = text.split()
    filtered_words = [w for w in words if w not in STOP_WORDS]
    return "".join(filtered_words)

def smart_search_clean(text):
    text = text.lower()
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'\b(480p|720p|1080p|2160p|4k|8k|hd|fhd|bluray|web-dl|webrip|camrip|dvdscr)\b', '', text)
    text = re.sub(r'\b(19|20)\d{2}\b', '', text)
    text = re.sub(r'\bs\d{1,2}(e\d{1,2})?\b', '', text)
    text = re.sub(r'\bseason\s?\d{1,2}\b', '', text)
    text = re.sub(r'\bepisode\s?\d{1,3}\b', '', text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    words = text.split()
    clean_words = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    return " ".join(clean_words).strip()

def extract_language(text):
    langs = ["Bengali", "Hindi", "English", "Tamil", "Telugu", "Korean"]
    return next((lang for lang in langs if lang.lower() in text.lower()), None)

def extract_year(text):
    match = re.search(r'\b(19|20)\d{2}\b', text)
    return int(match.group(0)) if match else None

def get_readable_time(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

def get_greeting():
    utc_now = datetime.now(timezone.utc)
    bd_hour = (utc_now.hour + 6) % 24
    if 5 <= bd_hour < 12: return "GOOD MORNING ☀️"
    elif 12 <= bd_hour < 17: return "GOOD AFTERNOON 🌤️"
    elif 17 <= bd_hour < 21: return "GOOD EVENING 🌇"
    else: return "GOOD NIGHT 🌙"

async def delete_message_later(chat_id, message_id, delay=300): 
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass

# ভেরিফিকেশন লিংক জেনারেটর
async def create_verification_link(message_id, user_id):
    token = secrets.token_urlsafe(16)
    await verify_col.insert_one({
        "token": token,
        "user_id": user_id,
        "movie_id": message_id,
        "step": 1,
        "created_at": datetime.now(timezone.utc)
    })
    return f"{BASE_URL}/verify/{token}"

# ------------------- External APIs -------------------

async def get_tmdb_suggestion(query):
    if not TMDB_API_KEY: return None
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(query)}&page=1"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("results"):
                        first_match = data["results"][0]
                        return first_match.get("title") or first_match.get("name") or first_match.get("original_title")
    except Exception as e:
        logger.error(f"TMDB Error: {e}")
    return None

def find_corrected_matches(query_clean, all_movie_titles_data, score_cutoff=80, limit=5):
    if not all_movie_titles_data:
        return []
    
    choices = [item["title_clean"] for item in all_movie_titles_data]
    matches_raw = process.extract(query_clean, choices, limit=limit, scorer=fuzz.token_set_ratio)
    
    corrected_suggestions = []
    seen_ids = set()
    
    for matched_clean_title, score in matches_raw:
        if score >= score_cutoff:
            for movie_data in all_movie_titles_data:
                if movie_data["title_clean"] == matched_clean_title:
                    if movie_data["message_id"] not in seen_ids:
                        corrected_suggestions.append({
                            "title": movie_data["original_title"],
                            "message_id": movie_data["message_id"],
                            "language": movie_data.get("language"),
                            "views_count": movie_data.get("views_count", 0),
                            "score": score
                        })
                        seen_ids.add(movie_data["message_id"])
                    break
                    
    return sorted(corrected_suggestions, key=lambda x: x["score"], reverse=True)

# ------------------- সিস্টেম ইঞ্জিন (Auto Msg & Broadcast) -------------------

async def auto_group_messenger():
    print("✅ অটো গ্রুপ মেসেজ সিস্টেম চালু হয়েছে...")
    while True:
        try:
            async for group in groups_col.find({}):
                chat_id = group["_id"]
                try:
                    sent = await app.send_message(chat_id, AUTO_MESSAGE_TEXT)
                    if sent:
                        asyncio.create_task(delete_message_later(chat_id, sent.id, delay=AUTO_MSG_DELETE_TIME))
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                except (PeerIdInvalid, UserIsBlocked):
                    await groups_col.delete_one({"_id": chat_id})
                except Exception:
                    pass
                await asyncio.sleep(1.5) 
        except Exception as e:
            logger.error(f"Auto Msg Error: {e}")
        
        await asyncio.sleep(AUTO_MSG_INTERVAL)

async def broadcast_messages(cursor, message_func, status_msg=None, total_users=0):
    success = 0
    failed = 0
    start_time = time.time()
    semaphore = asyncio.Semaphore(20)
    active_tasks = set()

    async def send_worker(user_id):
        nonlocal success, failed
        async with semaphore:
            try:
                await message_func(user_id)
                success += 1
            except FloodWait as e:
                await asyncio.sleep(e.value)
                try:
                    await message_func(user_id)
                    success += 1
                except Exception:
                    failed += 1
            except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid):
                await users_col.delete_one({"_id": user_id})
                failed += 1
            except Exception:
                failed += 1

    async def update_status_loop():
        while True:
            await asyncio.sleep(5)
            done = success + failed
            if total_users == 0 or done == 0: continue
            
            percentage = (done / total_users) * 100
            elapsed = time.time() - start_time
            if elapsed == 0: elapsed = 1
            speed = done / elapsed
            eta = (total_users - done) / speed if speed > 0 else 0
            
            progress_bar = f"[{'■' * int(percentage // 10)}{'□' * (10 - int(percentage // 10))}]"
            text = (
                f"🚀 **সুপারফাস্ট ব্রডকাস্ট চলছে...**\n\n"
                f"{progress_bar} **{percentage:.1f}%**\n"
                f"✅ সফল: `{success}` | ❌ ব্যর্থ: `{failed}`\n"
                f"⚡ স্পিড: `{speed:.1f} users/sec`\n"
                f"⏱ সময়: `{get_readable_time(elapsed)}`\n"
                f"⏳ বাকি সময়: `{get_readable_time(eta)}`"
            )
            try:
                if status_msg:
                    await (status_msg.edit_caption(text) if status_msg.photo else status_msg.edit_text(text))
            except Exception: pass
            
            if done >= total_users and not active_tasks:
                break

    updater_task = asyncio.create_task(update_status_loop())

    async for user in cursor:
        user_id = user["_id"]
        task = asyncio.create_task(send_worker(user_id))
        active_tasks.add(task)
        task.add_done_callback(active_tasks.discard)
        if len(active_tasks) > 50:
            await asyncio.sleep(0.1)
    
    while active_tasks:
        await asyncio.sleep(1)

    updater_task.cancel()
    elapsed = time.time() - start_time
    final_text = (
        f"✅ **ব্রডকাস্ট সম্পন্ন!**\n\n"
        f"👥 মোট ইউজার: `{total_users}`\n"
        f"✅ সফল: `{success}`\n"
        f"❌ ব্যর্থ: `{failed}`\n"
        f"⏱ সময় লেগেছে: `{get_readable_time(elapsed)}`"
    )
    if status_msg:
        try:
            await (status_msg.edit_caption(final_text) if status_msg.photo else status_msg.edit_text(final_text))
        except: pass

async def auto_broadcast_worker(movie_title, message_id, thumbnail_id=None):
    download_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("ডাউনলোড লিংক", url=f"https://t.me/{app.me.username}?start=watch_{message_id}")]
    ])
    notification_caption = f"🎬 **নতুন মুভি আপলোড হয়েছে!**\n\n**{movie_title}**\n\nএখনই ডাউনলোড করুন!"
    
    total_users = await users_col.count_documents({"notify": {"$ne": False}})
    if total_users == 0: return

    status_msg = None
    if ADMIN_IDS:
        try:
            pic_to_use = thumbnail_id if thumbnail_id else BROADCAST_PIC
            status_msg = await app.send_photo(ADMIN_IDS[0], photo=pic_to_use, caption=f"🚀 **অটো নোটিফিকেশন শুরু...**\n👥 ইউজার: `{total_users}`")
        except Exception: pass

    async def send_func(user_id):
        if thumbnail_id:
            msg = await app.send_photo(user_id, photo=thumbnail_id, caption=notification_caption, reply_markup=download_button)
        else:
            msg = await app.send_message(user_id, notification_caption, reply_markup=download_button)
        if msg: asyncio.create_task(delete_message_later(msg.chat.id, msg.id, delay=86400))

    cursor = users_col.find({"notify": {"$ne": False}}, {"_id": 1})
    await broadcast_messages(cursor, send_func, status_msg, total_users)

# ------------------- হ্যান্ডলার ও কমান্ডস -------------------

@app.on_message(filters.chat(CHANNEL_ID))
async def save_post(_, msg: Message):
    text = msg.text or msg.caption
    if not text: return
    
    thumbnail_file_id = None
    if msg.photo:
        thumbnail_file_id = msg.photo.file_id
    elif msg.video and msg.video.thumbs:
        thumbnail_file_id = msg.video.thumbs[0].file_id 

    movie_title = text.splitlines()[0]
    
    raw_data = {
        "message_id": msg.id,
        "title": movie_title, 
        "full_caption": text, 
        "date": msg.date,
        "year": extract_year(text),
        "language": extract_language(text),
        "title_clean": clean_text(text), 
        "views_count": 0,
        "thumbnail_id": thumbnail_file_id 
    }

    try:
        validated_data = movie_schema.load(raw_data)
        result = await movies_col.update_one(
            {"message_id": msg.id}, 
            {"$set": validated_data}, 
            upsert=True
        )
        if result.upserted_id is not None:
            setting = await settings_col.find_one({"key": "global_notify"})
            if setting and setting.get("value"):
                asyncio.create_task(auto_broadcast_worker(movie_title, msg.id, thumbnail_file_id))
    except ValidationError as err:
        logger.error(f"Schema Validation Error: {err.messages}")

@app.on_message(filters.group, group=10)
async def log_group(_, msg: Message):
    await groups_col.update_one(
        {"_id": msg.chat.id}, 
        {"$set": {"title": msg.chat.title, "active": True}}, 
        upsert=True
    )

@app.on_message(filters.command("start"))
async def start(_, msg: Message):
    user_id = msg.from_user.id
    current_time = datetime.now(timezone.utc)
    
    if user_id in user_last_start_time:
        if (current_time - user_last_start_time[user_id]) < timedelta(seconds=2):
            return
    user_last_start_time[user_id] = current_time

    await users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"joined": datetime.now(timezone.utc), "notify": True}},
        upsert=True
    )

    if len(msg.command) > 1:
        argument = msg.command[1]
        
        # --- VERIFICATION HANDLER (When Ads are ON) ---
        if argument.startswith("verified_"):
            token = argument.replace("verified_", "")
            verify_data = await verify_col.find_one({"token": token})

            if not verify_data:
                await msg.reply("❌ **লিংকটি মেয়াদোত্তীর্ণ!**\nদয়া করে আবার সার্চ করুন।", quote=True)
                return
            
            if verify_data["user_id"] != user_id:
                await msg.reply("⚠️ এই লিংকটি আপনার জন্য নয়!", quote=True)
                return

            if verify_data.get("step") != 2:
                await msg.reply("⚠️ **ভেরিফিকেশন অসম্পূর্ণ!**\nদয়া করে লিংকে ক্লিক করে ২য় ধাপ সম্পন্ন করুন।", quote=True)
                return

            message_id = verify_data["movie_id"]
            try:
                protect_setting = await settings_col.find_one({"key": "protect_forwarding"})
                should_protect = protect_setting.get("value", True) if protect_setting else True
                
                copied_message = await app.copy_message(
                    chat_id=msg.chat.id,        
                    from_chat_id=CHANNEL_ID,    
                    message_id=message_id,      
                    protect_content=should_protect 
                )
                
                await verify_col.delete_one({"token": token})
                await movies_col.update_one({"message_id": message_id}, {"$inc": {"views_count": 1}})
                
                action_buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚠️ রিপোর্ট / সমস্যা", callback_data=f"report_{message_id}")]
                ])
                suc_msg = await msg.reply("✅ **ভেরিফিকেশন সফল!**\nআপনার ফাইল উপরে দেওয়া হয়েছে।", reply_markup=action_buttons)
                asyncio.create_task(delete_message_later(suc_msg.chat.id, suc_msg.id, 60))
                
            except Exception:
                await msg.reply("❌ মুভিটি খুঁজে পাওয়া যাচ্ছে না (সম্ভবত ডিলিট হয়ে গেছে)।")
            return
            
        # --- DIRECT LINK HANDLER (When Ads are OFF) ---
        elif argument.startswith("watch_"):
            message_id = int(argument.replace("watch_", ""))
            try:
                protect_setting = await settings_col.find_one({"key": "protect_forwarding"})
                should_protect = protect_setting.get("value", True) if protect_setting else True
                
                await app.copy_message(msg.chat.id, CHANNEL_ID, message_id, protect_content=should_protect)
                await movies_col.update_one({"message_id": message_id}, {"$inc": {"views_count": 1}})
            except:
                await msg.reply("❌ Error fetching file.")
            return

    # সাধারণ ওয়েলকাম মেসেজ
    greeting = get_greeting()
    user_mention = msg.from_user.mention
    bot_username = app.me.username
    
    start_caption = f"""
HEY {user_mention}, {greeting}

🤖 **I AM {app.me.first_name},** THE MOST
POWERFUL AUTO FILTER BOT WITH 
WEB VERIFICATION SYSTEM.
"""
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔰 ADD ME TO YOUR GROUP 🔰", url=f"https://t.me/{bot_username}?startgroup=true")],
        [
            InlineKeyboardButton("HELP 📢", callback_data="help_menu"),
            InlineKeyboardButton("ABOUT 📘", callback_data="about_menu")
        ],
        [
            InlineKeyboardButton("TOP SEARCHING ⭐", callback_data="top_searching"),
            InlineKeyboardButton("UPGRADE 🎟️", url=UPDATE_CHANNEL)
        ]
    ])

    await msg.reply_photo(photo=START_PIC, caption=start_caption, reply_markup=btns)

# ------------------- অ্যাডমিন কমান্ড (Toggle Verification included) -------------------

@app.on_message(filters.command("verify") & filters.user(ADMIN_IDS))
async def toggle_verification(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        await msg.reply("ব্যবহার:\n`/verify on` - ওয়েবসাইট ভেরিফিকেশন চালু (Ads অন)\n`/verify off` - ডাইরেক্ট ফাইল (Ads অফ)")
        return
    
    new_status = True if msg.command[1] == "on" else False
    await settings_col.update_one({"key": "verification_mode"}, {"$set": {"value": new_status}}, upsert=True)
    
    text = "✅ **ভেরিফিকেশন মোড চালু হয়েছে!**\nএখন ইউজাররা ওয়েবসাইট হয়ে ফাইল পাবে।" if new_status else "🚫 **ভেরিফিকেশন মোড বন্ধ হয়েছে!**\nএখন ইউজাররা সরাসরি ফাইল পাবে।"
    await msg.reply(text)

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg: Message):
    if not msg.reply_to_message and len(msg.command) < 2:
        await msg.reply("ব্যবহার:\n১. কোনো মেসেজে রিপ্লাই দিয়ে `/broadcast` লিখুন।\n২. অথবা `/broadcast আপনার মেসেজ` লিখুন।")
        return
    
    reply_msg = msg.reply_to_message
    broadcast_text = None
    origin_chat_id = None
    origin_message_id = None
    
    if reply_msg:
        origin_chat_id = reply_msg.chat.id
        origin_message_id = reply_msg.id
    else:
        full_text = msg.text or msg.caption
        if not full_text:
             await msg.reply("❌ কোনো টেক্সট পাওয়া যায়নি।")
             return
        broadcast_text = full_text.split(None, 1)[1]

    total_users = await users_col.count_documents({})
    if total_users == 0:
        await msg.reply("ডাটাবেসে কোনো ইউজার নেই।")
        return
        
    status_msg = await msg.reply_photo(photo=BROADCAST_PIC, caption=f"🚀 **ম্যানুয়াল ব্রডকাস্ট শুরু...**\n👥 টার্গেট: `{total_users}`")
    cursor = users_col.find({}, {"_id": 1})

    async def send_func(user_id):
        if reply_msg:
            await app.copy_message(user_id, origin_chat_id, origin_message_id)
        else:
            await app.send_message(user_id, broadcast_text, disable_web_page_preview=True)

    asyncio.create_task(broadcast_messages(cursor, send_func, status_msg, total_users))

@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg: Message):
    if len(msg.command) < 2:
        await msg.reply("অনুগ্রহ করে /feedback এর পর আপনার মতামত লিখুন।")
        return
    await feedback_col.insert_one({
        "user": msg.from_user.id,
        "text": msg.text.split(None, 1)[1],
        "time": datetime.now(timezone.utc)
    })
    m = await msg.reply("আপনার মতামতের জন্য ধন্যবাদ!")
    asyncio.create_task(delete_message_later(m.chat.id, m.id))

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg: Message):
    total_groups = await groups_col.count_documents({})
    total_users = await users_col.count_documents({})
    total_movies = await movies_col.count_documents({})
    total_feedback = await feedback_col.count_documents({})
    total_requests = await requests_col.count_documents({})
    
    stats_msg = await msg.reply(
        f"মোট ব্যবহারকারী: {total_users}\nমোট গ্রুপ: {total_groups}\nমোট মুভি: {total_movies}\nমোট ফিডব্যাক: {total_feedback}\nমোট অনুরোধ: {total_requests}"
    )
    asyncio.create_task(delete_message_later(stats_msg.chat.id, stats_msg.id))

@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify_command(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        await msg.reply("ব্যবহার: /notify on অথবা /notify off")
        return
    new_value = True if msg.command[1] == "on" else False
    await settings_col.update_one({"key": "global_notify"}, {"$set": {"value": new_value}}, upsert=True)
    status = "চালু" if new_value else "বন্ধ"
    await msg.reply(f"✅ গ্লোবাল নোটিফিকেশন {status} করা হয়েছে!")

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_specific_movie(_, msg: Message):
    if len(msg.command) < 2:
        await msg.reply("টাইটেল দিন। ব্যবহার: `/delete_movie <নাম>`")
        return
    title = msg.text.split(None, 1)[1].strip()
    movie = await movies_col.find_one({"title": {"$regex": re.escape(title), "$options": "i"}})
    
    if movie:
        await movies_col.delete_one({"_id": movie["_id"]})
        await msg.reply(f"মুভি **{movie['title']}** ডিলিট করা হয়েছে।")
    else:
        await msg.reply(f"**{title}** পাওয়া যায়নি।")

@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies_command(_, msg: Message):
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("হ্যাঁ, সব ডিলিট করুন", callback_data="confirm_delete_all_movies")],
        [InlineKeyboardButton("না, বাতিল করুন", callback_data="cancel_delete_all_movies")]
    ])
    await msg.reply("সব মুভি ডিলিট করতে চান? এটি অপরিবর্তনীয়!", reply_markup=btn)

@app.on_message(filters.command("request") & filters.private)
async def request_movie(_, msg: Message):
    if len(msg.command) < 2:
        await msg.reply("ব্যবহার: `/request <মুভির নাম>`", quote=True)
        return
    movie_name = msg.text.split(None, 1)[1].strip()
    user_id = msg.from_user.id
    username = msg.from_user.username or msg.from_user.first_name
    
    await requests_col.insert_one({
        "user_id": user_id,
        "username": username,
        "movie_name": movie_name,
        "request_time": datetime.now(timezone.utc),
        "status": "pending"
    })
    
    m = await msg.reply(f"**'{movie_name}'** অনুরোধ সফলভাবে জমা হয়েছে।", quote=True)
    asyncio.create_task(delete_message_later(m.chat.id, m.id))
    
    encoded_name = urllib.parse.quote_plus(movie_name)
    admin_btns = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ সম্পন্ন", callback_data=f"req_fulfilled_{user_id}_{encoded_name}"),
        InlineKeyboardButton("❌ বাতিল", callback_data=f"req_rejected_{user_id}_{encoded_name}")
    ]])
    for admin_id in ADMIN_IDS:
        try:
            await app.send_message(admin_id, f"❗ *নতুন অনুরোধ!*\n🎬 `{movie_name}`\n👤 [{username}](tg://user?id={user_id})", reply_markup=admin_btns)
        except: pass

# ------------------- স্মার্ট সার্চ হ্যান্ডলার (With Toggle Logic) -------------------

@app.on_message(filters.text & ~filters.command(["start", "verify", "broadcast", "stats", "feedback", "request", "popular", "notify", "delete_movie", "delete_all_movies", "forward_toggle"]) & (filters.group | filters.private))
async def search(_, msg: Message):
    query = msg.text.strip()
    if not query: return
    
    if msg.chat.type in ["group", "supergroup"]:
        await groups_col.update_one({"_id": msg.chat.id}, {"$set": {"title": msg.chat.title, "active": True}}, upsert=True)
        if len(query) < 2 or msg.reply_to_message or msg.from_user.is_bot: return
        if query.startswith("/"): return

    user_id = msg.from_user.id
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"last_query": query}, "$setOnInsert": {"joined": datetime.now(timezone.utc)}},
        upsert=True
    )

    loading_message = await msg.reply("🔎 <b>Searching...</b>", quote=True)
    
    raw_year = extract_year(query)
    cleaned_query = smart_search_clean(query)
    if not cleaned_query: cleaned_query = query.lower()

    search_source = ""
    results = []
    
    regex_pattern = r"\b" + re.escape(cleaned_query) + r"\b"
    query_filter = {
        "$or": [
            {"title_clean": {"$regex": regex_pattern, "$options": "i"}},
            {"title": {"$regex": regex_pattern, "$options": "i"}}
        ]
    }
    if raw_year: query_filter["year"] = raw_year
    
    db_cursor = movies_col.find(query_filter).sort("views_count", -1).limit(RESULTS_COUNT)
    results = await db_cursor.to_list(length=RESULTS_COUNT)

    if not results and not raw_year:
        loose_pattern = re.escape(cleaned_query)
        db_cursor = movies_col.find({
            "title_clean": {"$regex": loose_pattern, "$options": "i"}
        }).sort("views_count", -1).limit(RESULTS_COUNT)
        results = await db_cursor.to_list(length=RESULTS_COUNT)

    tmdb_detected_title = None
    if not results:
        tmdb_detected_title = await get_tmdb_suggestion(cleaned_query)
        if tmdb_detected_title:
            tmdb_clean = clean_text(tmdb_detected_title)
            db_cursor = movies_col.find({
                "$or": [
                    {"title_clean": {"$regex": re.escape(tmdb_clean), "$options": "i"}},
                    {"title": {"$regex": re.escape(tmdb_detected_title), "$options": "i"}}
                ]
            }).sort("views_count", -1).limit(RESULTS_COUNT)
            results = await db_cursor.to_list(length=RESULTS_COUNT)
            if results: search_source = f"✅ **Auto Corrected:** '{tmdb_detected_title}'"

    if not results and not raw_year and not tmdb_detected_title:
        all_movie_data = await movies_col.find({}, {"title_clean": 1, "original_title": "$title", "message_id": 1, "views_count": 1}).to_list(length=None)
        corrected_suggestions = await asyncio.get_event_loop().run_in_executor(
            thread_pool_executor, find_corrected_matches, cleaned_query, all_movie_data, 80, RESULTS_COUNT
        )
        if corrected_suggestions:
            results = corrected_suggestions
            search_source = f"🤔 আপনি কি **{corrected_suggestions[0]['title']}** খুঁজছেন?"

    if results:
        await loading_message.delete()
        header_text = f"🎬 **আপনার মুভি পাওয়া গেছে:**\n{search_source}" if search_source else "🎬 **আপনার মুভি পাওয়া গেছে:**"
        await send_results(msg, results, header_text)
        return

    # কিছু না পেলে
    await loading_message.delete()
    final_query = tmdb_detected_title if tmdb_detected_title else cleaned_query
    encoded_final_query = urllib.parse.quote_plus(final_query)
    Google_Search_url = "https://www.google.com/search?q=" + urllib.parse.quote(final_query)
    
    req_btn = InlineKeyboardButton(f"✅ রিকোয়েস্ট করুন", callback_data=f"request_movie_{user_id}_{encoded_final_query}")
    google_btn = InlineKeyboardButton("🌐 গুগলে দেখুন", url=Google_Search_url)
    
    alert_text = (
        f"❌ **'{query}'** পাওয়া যায়নি।\n"
        f"💡 **আপনি কি এটি খুঁজছিলেন?** 👉 **{tmdb_detected_title}**\n\n"
        f"রিকোয়েস্ট করতে নিচের বাটনে ক্লিক করুন।"
    ) if tmdb_detected_title else f"❌ দুঃখিত! **'{cleaned_query}'** পাওয়া যায়নি।"

    alert = await msg.reply_text(alert_text, reply_markup=InlineKeyboardMarkup([[req_btn], [google_btn]]), quote=True)
    asyncio.create_task(delete_message_later(alert.chat.id, alert.id))

async def send_results(msg, results, header="🎬 আপনার মুভি পাওয়া গেছে:"):
    # ডাটাবেস থেকে সেটিং চেক (ভেরিফিকেশন অন/অফ)
    setting = await settings_col.find_one({"key": "verification_mode"})
    is_verify_on = setting.get("value", True) if setting else True
    
    buttons = []
    user_id = msg.from_user.id
    
    for movie in results:
        title = movie.get('title') or movie.get('original_title')
        mid = movie['message_id']
        
        if is_verify_on:
            # ভেরিফিকেশন অন: ওয়েবসাইটের লিংক (Flask)
            link = await create_verification_link(mid, user_id)
        else:
            # ভেরিফিকেশন অফ: ডাইরেক্ট টেলিগ্রাম স্টার্ট লিংক
            bot_username = app.me.username
            link = f"https://t.me/{bot_username}?start=watch_{mid}"
        
        buttons.append([
            InlineKeyboardButton(
                text=f"{title[:35]}...",
                url=link
            )
        ])
    
    footer = "👇 নিচের লিংকে ক্লিক করে ভেরিফাই করুন:" if is_verify_on else "👇 ডাউনলোড করতে ক্লিক করুন:"
    final_text = f"{header}\n{footer}"
    
    m = await msg.reply(final_text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    asyncio.create_task(delete_message_later(m.chat.id, m.id))

# ------------------- Callback Handlers -------------------

@app.on_callback_query(filters.regex(r"^noresult_"))
async def handle_admin_reply(_, cq: CallbackQuery):
    await cq.answer("Command Received")

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data
    
    if data == "home_menu":
        await cq.message.edit_caption(caption="Main Menu", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Help", callback_data="help_menu")]]))
    
    elif data == "help_menu":
        await cq.message.edit_caption(caption="Help Menu", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="home_menu")]]))
        
    elif data.startswith("report_"):
        await cq.answer("Report Sent!", show_alert=True)
        
    elif data == "confirm_delete_all_movies":
        await movies_col.delete_many({})
        await cq.message.edit_text("✅ All Deleted!")

    elif data == "cancel_delete_all_movies":
        await cq.message.edit_text("❌ Cancelled!")

    # ------------------- REQUEST SYSTEM (6 Button Admin Panel) -------------------
    # ইউজার রিকোয়েস্ট করলে এডমিনের কাছে ৬টি বাটনসহ যাবে
    elif data.startswith("request_movie_"):
        try:
            _, user_id_str, movie_name_encoded = data.split("_", 2)
            user_id = int(user_id_str)
            movie_name = urllib.parse.unquote_plus(movie_name_encoded)
            
            await cq.answer("✅ আপনার রিকোয়েস্ট এডমিনের কাছে পাঠানো হয়েছে!", show_alert=True)
            await cq.message.edit_text(f"✅ **রিকোয়েস্ট সফল!**\n\n🎬 মুভি: `{movie_name}`\n\nঅনুগ্রহ করে অপেক্ষা করুন, এডমিন শীঘ্রই এটি আপলোড করবেন।")

            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📤 Uploading", callback_data=f"rep_uploading_{user_id}_{movie_name_encoded}"),
                    InlineKeyboardButton("✅ Uploaded", callback_data=f"rep_uploaded_{user_id}_{movie_name_encoded}")
                ],
                [
                    InlineKeyboardButton("❌ Unavailable", callback_data=f"rep_unavailable_{user_id}_{movie_name_encoded}"),
                    InlineKeyboardButton("🕵️ Already Available", callback_data=f"rep_already_{user_id}_{movie_name_encoded}")
                ],
                [
                    InlineKeyboardButton("⚠️ Spelling Error", callback_data=f"rep_spelling_{user_id}_{movie_name_encoded}"),
                    InlineKeyboardButton("🗑 Delete Msg", callback_data=f"rep_delete_{user_id}_{movie_name_encoded}")
                ]
            ])

            user = await app.get_users(user_id)
            user_mention = user.mention if user else f"User ID: {user_id}"

            admin_msg_text = (
                f"🔔 **নতুন মুভি রিকোয়েস্ট!**\n\n"
                f"👤 রিকোয়েস্টকারী: {user_mention}\n"
                f"🎬 মুভির নাম: `{movie_name}`\n\n"
                f"👇 নিচের বাটন দিয়ে রিপ্লাই দিন:"
            )

            for admin_id in ADMIN_IDS:
                try:
                    await app.send_message(chat_id=admin_id, text=admin_msg_text, reply_markup=buttons)
                except Exception as e:
                    logger.error(f"Failed to send request to admin {admin_id}: {e}")

        except Exception as e:
            logger.error(f"Request Error: {e}")

    # এডমিন বাটনে ক্লিক করলে ইউজারের কাছে রিপ্লাই যাবে
    elif data.startswith("rep_"):
        try:
            _, action, user_id_str, movie_name_encoded = data.split("_", 3)
            user_id = int(user_id_str)
            movie_name = urllib.parse.unquote_plus(movie_name_encoded)
            
            user_msg = ""
            admin_feedback = ""

            if action == "uploading":
                user_msg = f"👋 হ্যালো!\n\nআপনার রিকোয়েস্ট করা মুভি **'{movie_name}'** আপলোড করা হচ্ছে।\nকিছুক্ষণ পর আবার সার্চ করুন। 📤"
                admin_feedback = "✅ আপনি 'Uploading' মার্ক করেছেন।"
            
            elif action == "uploaded":
                user_msg = f"👋 হ্যালো!\n\nআপনার রিকোয়েস্ট করা মুভি **'{movie_name}'** আপলোড করা হয়েছে! ✅\nএখনই বট থেকে সার্চ করে নামিয়ে নিন।"
                admin_feedback = "✅ আপনি 'Uploaded' মার্ক করেছেন।"

            elif action == "unavailable":
                user_msg = f"😔 দুঃখিত!\n\nআপনার রিকোয়েস্ট করা **'{movie_name}'** মুভিটি বর্তমানে পাওয়া যাচ্ছে না। ❌"
                admin_feedback = "✅ আপনি 'Unavailable' মার্ক করেছেন।"

            elif action == "already":
                user_msg = f"🔍 হ্যালো!\n\nমুভিটি **'{movie_name}'** ইতিমধ্যে আমাদের চ্যানেলে আছে।\nদয়া করে ভালো করে বানান চেক করে আবার সার্চ করুন। 🕵️"
                admin_feedback = "✅ আপনি 'Already Available' মার্ক করেছেন।"

            elif action == "spelling":
                user_msg = f"⚠️ হ্যালো!\n\nআপনার রিকোয়েস্ট করা মুভির বানান ভুল মনে হচ্ছে।\nদয়া করে সঠিক বানান (**English**) লিখে আবার সার্চ করুন।"
                admin_feedback = "✅ আপনি 'Spelling Error' মার্ক করেছেন।"

            elif action == "delete":
                await cq.message.delete()
                return

            try:
                await app.send_message(chat_id=user_id, text=user_msg)
            except Exception:
                admin_feedback += "\n(কিন্তু ইউজারকে মেসেজ পাঠানো যায়নি)"

            await cq.message.edit_text(f"🔒 **রিকোয়েস্ট ক্লোজড!**\n🎬 মুভি: `{movie_name}`\n👮 একশন নিয়েছেন: {cq.from_user.mention}\n📝 স্ট্যাটাস: {admin_feedback}")

        except Exception as e:
            logger.error(f"Admin Reply Error: {e}")

user_last_start_time = {}

if __name__ == "__main__":
    print("🚀 Bot Started with Toggle Verification & 6-Button Request System...")
    app.loop.create_task(init_settings())
    app.loop.create_task(auto_group_messenger())
    app.run()
