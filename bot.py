#
# ----------------------------------------------------
# Developed by: Ctgmovies23
# Project: TGLinkBase Auto Filter Bot (Ultimate Edition)
# Version: 6.1 (Fixed Pagination + Filters + Robust Broadcast)
# Features:
#   - Auto Filter (MongoDB)
#   - Multi-Channel Indexing (ID Batch Fetching)
#   - Safe Bulk Delete (Preview & Confirm)
#   - Web Verification (Flask + Ads)
#   - Content Protection (Forward Block)
#   - Auto Admin Notification
#   - Auto Broadcast & Group Messenger
#   - Smart Search (TMDB + Spelling Correction)
#   - Supports Direct Files & Poster Link Posts
#   - UI: Working Quality, Language, Season Filters
#   - UI: Smooth Page Navigation (In-Place Edit)
#   - FIXED: Robust Manual Broadcast System
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

# ------------------- EXTERNAL LIBRARIES -------------------
import ujson  # For Fast JSON parsing
import aiohttp # For Async Web Requests (TMDB/API)
from flask import Flask # For Web Verification Server

# ------------------- PYROGRAM -------------------
from pyrogram import Client, filters
from pyrogram.types import (
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery,
    InputMediaPhoto
)
from pyrogram.errors import (
    FloodWait, 
    InputUserDeactivated, 
    UserIsBlocked, 
    PeerIdInvalid, 
    MessageNotModified, 
    ChannelInvalid
)

# ------------------- DATABASE & LOGIC -------------------
from motor.motor_asyncio import AsyncIOMotorClient # Async MongoDB
from pymongo import MongoClient, ASCENDING # Sync MongoDB (For Indexing)
from fuzzywuzzy import process, fuzz # Fuzzy Logic for Spelling
from marshmallow import Schema, fields, ValidationError # Schema Validation

# ==============================================================================
#                               CONFIGURATIONS
# ==============================================================================

# Telegram API & Bot Token
API_ID = int(os.getenv("API_ID", "0")) 
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Channels & Admins
# Primary Channel for default uploads
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0")) 
# Admin IDs (comma separated)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
# Channel to redirect for updates
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/TGLinkBase")

# Database
DATABASE_URL = os.getenv("DATABASE_URL")

# Search Settings
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
TMDB_API_KEY = os.getenv("TMDB_API_KEY") 

# Images
START_PIC = os.getenv("START_PIC", "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg")
BROADCAST_PIC = os.getenv("BROADCAST_PIC", "https://telegra.ph/file/18659550b694b47000787.jpg")

# Web & Ads Settings
BASE_URL = os.getenv("BASE_URL", "http://localhost:8080") 

# Ad Codes (Full HTML allowed)
AD_CODE_HEAD = os.getenv("AD_CODE_HEAD", "") 
AD_CODE_TOP = os.getenv("AD_CODE_TOP", "")   
AD_CODE_BODY = os.getenv("AD_CODE_BODY", """
<div style="text-align: center; color: #ffaa00; margin: 20px auto; border: 2px dashed #444; padding: 15px; background: #222; border-radius: 10px;">
    <h3>⬇️ Advertisement Area ⬇️</h3>
    <p>Place your ad codes here from Koyeb Variables</p>
</div>
""") 
AD_CODE_BOTTOM = os.getenv("AD_CODE_BOTTOM", "") 

# Auto Group Message Settings
AUTO_MSG_INTERVAL = 1200  # 20 Minutes
AUTO_MSG_DELETE_TIME = 300 # 5 Minutes

AUTO_MESSAGE_TEXT = """
🎬✨ **নিয়মিত মুভি আপডেট!** ✨🎬

🍿 নতুন মুভি ও ওয়েব সিরিজের জন্য সবসময় আমাদের সাথে থাকুন।
🔎 আপনার পছন্দের মুভি খুঁজতে শুধু নাম লিখে সার্চ করুন।

🚀 **দ্রুত আপডেট পেতে জয়েন করুন:**
👉 @TGLinkBase

💡 _মুভি মিস করবেন না, সবকিছু এক জায়গায়!_
"""

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==============================================================================
#                               DATABASE SETUP
# ==============================================================================

try:
    # Async Client for Bot Operations
    motor_client = AsyncIOMotorClient(DATABASE_URL)
    db = motor_client["movie_bot"]

    movies_col = db["movies"]
    users_col = db["users"]
    groups_col = db["groups"]
    settings_col = db["settings"]
    requests_col = db["requests"]
    feedback_col = db["feedback"]
    verify_col = db["verification"] 

    # Sync Client for Indexing & TTL
    sync_client = MongoClient(DATABASE_URL)
    sync_db = sync_client["movie_bot"]
    
    # Creating Indexes for Faster Search
    # Note: Removed unique=True from message_id to allow same message_id from different channels
    sync_db.movies.create_index([("title_clean", ASCENDING)], background=True)
    sync_db.movies.create_index("language", background=True)
    sync_db.movies.create_index([("views_count", ASCENDING)], background=True)
    sync_db.movies.create_index([("chat_id", ASCENDING)], background=True) # New for multi-channel
    
    # TTL Index (Verification Token expires after 1 hour)
    sync_db.verification.create_index("created_at", expireAfterSeconds=3600)
    
    print("✅ Database Connected & Indexes Created Successfully!")
except Exception as e:
    print(f"⚠️ Database Connection Error: {e}")
    exit()

# Data Validation Schema
class MovieSchema(Schema):
    chat_id = fields.Int(required=True) # Source Channel ID
    message_id = fields.Int(required=True) # Message ID
    title = fields.Str(required=True)
    title_clean = fields.Str(required=True)
    full_caption = fields.Str(allow_none=True)
    year = fields.Int(allow_none=True)
    language = fields.Str(allow_none=True)
    views_count = fields.Int(load_default=0)
    thumbnail_id = fields.Str(allow_none=True)
    date = fields.DateTime()

movie_schema = MovieSchema()

# Initialize Default Settings
async def init_settings():
    try:
        await settings_col.update_one({"key": "protect_content"}, {"$setOnInsert": {"value": True}}, upsert=True)
        await settings_col.update_one({"key": "verification_mode"}, {"$setOnInsert": {"value": True}}, upsert=True)
        await settings_col.update_one({"key": "global_notify"}, {"$setOnInsert": {"value": True}}, upsert=True)
    except Exception as e:
        logger.error(f"Settings Init Error: {e}")

# ==============================================================================
#                           FLASK WEB SERVER (VERIFICATION)
# ==============================================================================

flask_app = Flask(__name__)

# Full HTML Template
def get_verification_html(heading, timer_seconds, next_link, btn_text):
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Secure Link Verification</title>
        <style>
            :root {{
                --primary-color: #00ff88;
                --bg-color: #121212;
                --card-bg: #1e1e1e;
                --text-color: #e0e0e0;
            }}
            body {{
                background-color: var(--bg-color);
                color: var(--text-color);
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                text-align: center;
                padding: 10px;
            }}
            .container {{
                background: var(--card-bg);
                padding: 30px;
                border-radius: 16px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
                max-width: 100%;
                width: 450px;
                border: 1px solid #333;
                margin-top: 20px;
                margin-bottom: 20px;
            }}
            h2 {{
                color: var(--primary-color);
                margin-bottom: 15px;
                font-size: 24px;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            p {{
                font-size: 16px;
                margin-bottom: 20px;
                color: #aaa;
            }}
            
            /* Ad Slots */
            .ad-box {{
                width: 100%;
                margin: 20px 0;
                display: flex;
                justify-content: center;
                align-items: center;
                overflow: hidden;
                background: #000;
                border-radius: 8px;
                min-height: 50px;
            }}
            .ad-box img, .ad-box iframe {{
                max-width: 100%;
                height: auto;
            }}

            .timer-box {{
                font-size: 20px;
                font-weight: bold;
                color: #ffaa00;
                margin: 20px 0;
                padding: 15px;
                background: #2a2a2a;
                border-radius: 8px;
                border: 2px dashed #555;
            }}
            .btn {{
                display: none;
                background: linear-gradient(135deg, #007bff, #0056b3);
                color: white;
                padding: 16px 30px;
                text-decoration: none;
                font-size: 18px;
                border-radius: 50px;
                font-weight: bold;
                transition: transform 0.2s, box-shadow 0.2s;
                width: 100%;
                box-sizing: border-box;
                margin-top: 15px;
                box-shadow: 0 4px 15px rgba(0, 123, 255, 0.4);
            }}
            .btn:hover {{
                transform: scale(1.03);
                box-shadow: 0 6px 20px rgba(0, 123, 255, 0.6);
            }}
            footer {{
                margin-top: 30px;
                font-size: 12px;
                color: #555;
            }}
        </style>
        <!-- Adsterra Head Code -->
        {AD_CODE_HEAD}
    </head>
    <body>
        
        <!-- 1. TOP AD -->
        <div class="ad-box">
            {AD_CODE_TOP}
        </div>

        <div class="container">
            <h2>🛡️ Secure Verification</h2>
            <p>{heading}</p>
            
            <!-- 2. MIDDLE AD -->
            <div class="ad-box">
                {AD_CODE_BODY}
            </div>

            <div class="timer-box">
                Please Wait: <span id="count">{timer_seconds}</span> seconds
            </div>
            
            <a id="actionBtn" href="{next_link}" class="btn">{btn_text}</a>
            
            <!-- 3. BOTTOM AD -->
            <div class="ad-box">
                {AD_CODE_BOTTOM}
            </div>

            <footer>
                Powered by TGLinkBase &bull; 100% Safe & Secure
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
    return "Bot & Web Server is Running Successfully! 🚀"

@flask_app.route("/verify/<token>")
def verify_page_one(token):
    # Validate Token
    data = sync_db.verification.find_one({"token": token})
    if not data:
        return "❌ <b>Invalid or Expired Link!</b><br>Please go back to Telegram and search again."

    # Page 1
    next_url = f"{BASE_URL}/verify/step2/{token}"
    return get_verification_html(
        heading="Step 1/2: Verifying your request...",
        timer_seconds=10,
        next_link=next_url,
        btn_text="Next Step 🚀"
    )

@flask_app.route("/verify/step2/<token>")
def verify_page_two(token):
    # Update Step
    res = sync_db.verification.update_one({"token": token}, {"$set": {"step": 2}})
    if res.matched_count == 0:
        return "❌ <b>Session Expired!</b><br>Please search again."

    # Page 2
    bot_username = app.me.username if app.me else "TGLinkBaseBot" 
    final_link = f"https://t.me/{bot_username}?start=verified_{token}"

    return get_verification_html(
        heading="Step 2/2: Generating Download Link...",
        timer_seconds=10,
        next_link=final_link,
        btn_text="GET FILE NOW ✅"
    )

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

# ==============================================================================
#                           BOT UTILITIES & HELPERS
# ==============================================================================

# Thread Pool for Fuzzy Search
thread_pool_executor = ThreadPoolExecutor(max_workers=5)

# Pyrogram Client Initialization
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Stop Words for Cleaning Titles
STOP_WORDS = [
    "movie", "movies", "film", "films", "cinema", "show", "series", "season", "episode", 
    "full", "link", "links", "download", "watch", "online", "free", "all", "part", "url",
    "hindi", "bengali", "bangla", "english", "tamil", "telugu", "kannada", "malayalam", 
    "korean", "japanese", "chinese", "spanish", "french", "dubbed", "dual", "audio", 
    "sub", "esub", "subbed", "org", "original",
    "hd", "fhd", "4k", "8k", "1080p", "720p", "480p", "360p", "240p", 
    "cam", "hdcam", "rip", "web", "webrip", "hdrip", "bluray", "dvd", "dvdscr", 
    "hevc", "x264", "x265", "10bit", "60fps", "hdr", "amzn", "nf", "hulu", "mp4", "mkv"
]

def clean_text(text):
    """Cleans text for database indexing."""
    text = text.lower()
    text = re.sub(r'(?<!\d)(19|20)\d{2}(?!\d)', '', text) 
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    words = text.split()
    filtered_words = [w for w in words if w not in STOP_WORDS]
    return "".join(filtered_words)

def smart_search_clean(text):
    """Cleans user query for searching."""
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

# Create Web Verification Link
async def create_verification_link(message_id, user_id):
    token = secrets.token_urlsafe(16)
    
    # Need to fetch the movie to get correct chat_id
    movie = await movies_col.find_one({"message_id": message_id})
    # Default to CHANNEL_ID if not found (backward compatibility)
    chat_id = movie["chat_id"] if movie else CHANNEL_ID

    await verify_col.insert_one({
        "token": token,
        "user_id": user_id,
        "movie_id": message_id,
        "chat_id": chat_id, # Storing chat_id is crucial for multi-channel
        "step": 1,
        "created_at": datetime.now(timezone.utc)
    })
    return f"{BASE_URL}/verify/{token}"

# TMDB Fallback Search
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

# Fuzzy Matching for Spelling Correction
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

# Helper function to consolidate search logic and allow Pagination
async def get_search_results(query, offset=0):
    """
    Executes the search logic (Regex > TMDB > Fuzzy).
    Returns (results_list, total_count, search_source, cleaned_query, tmdb_detected_title)
    """
    raw_year = extract_year(query)
    cleaned_query = smart_search_clean(query)
    # If cleaned query is empty (e.g. only '720p' was typed), use original lower query
    if not cleaned_query: cleaned_query = query.lower()

    # Note: If user added a filter (e.g. "Avengers 720p"), smart_search_clean removes "720p".
    # But we want to support filters. So we check if the original query has filter words.
    # To make filters work without breaking smart clean, we use the raw query for Regex if smart clean seems too short.
    
    # Improved Search Logic for Filters:
    # We will search using regex on BOTH 'title_clean' AND 'title' fields.
    # If the user typed "Avengers 720p", cleaned_query might just be "avengers". 
    # But we want to respect "720p".
    # So we use the query string passed to this function for regex.
    
    search_query_regex = re.escape(query.strip()) # Use the full query (with filters)
    
    search_source = ""
    results = []
    total_count = 0

    # 1. Direct Regex Search (Matches Title OR Clean Title)
    # This supports "Avengers 720p" matching against "Avengers: Endgame (2019) [720p]"
    query_filter = {
        "$or": [
            {"title_clean": {"$regex": search_query_regex, "$options": "i"}},
            {"title": {"$regex": search_query_regex, "$options": "i"}}
        ]
    }
    if raw_year: query_filter["year"] = raw_year
    
    # Get total count first for pagination
    total_count = await movies_col.count_documents(query_filter)
    
    if total_count > 0:
        cursor = movies_col.find(query_filter).sort("views_count", -1).skip(offset).limit(RESULTS_COUNT)
        results = await cursor.to_list(length=RESULTS_COUNT)
    
    # 2. Loose Search (only if no direct results found & no specific year filter)
    if not results and not raw_year:
        # Fallback to cleaned query
        loose_pattern = re.escape(cleaned_query)
        loose_filter = {"title_clean": {"$regex": loose_pattern, "$options": "i"}}
        
        total_count = await movies_col.count_documents(loose_filter)
        
        if total_count > 0:
            cursor = movies_col.find(loose_filter).sort("views_count", -1).skip(offset).limit(RESULTS_COUNT)
            results = await cursor.to_list(length=RESULTS_COUNT)

    # 3. TMDB Search (only on first page)
    tmdb_detected_title = None
    if not results and offset == 0: 
        tmdb_detected_title = await get_tmdb_suggestion(cleaned_query)
        if tmdb_detected_title:
            tmdb_clean = clean_text(tmdb_detected_title)
            tmdb_filter = {
                "$or": [
                    {"title_clean": {"$regex": re.escape(tmdb_clean), "$options": "i"}},
                    {"title": {"$regex": re.escape(tmdb_detected_title), "$options": "i"}}
                ]
            }
            total_count = await movies_col.count_documents(tmdb_filter)
            if total_count > 0:
                cursor = movies_col.find(tmdb_filter).sort("views_count", -1).limit(RESULTS_COUNT)
                results = await cursor.to_list(length=RESULTS_COUNT)
                search_source = f"✅ **Auto Corrected:** '{tmdb_detected_title}'"

    # 4. Fuzzy Search (Last Resort)
    if not results and not raw_year and not tmdb_detected_title and offset == 0:
        all_movie_data = await movies_col.find({}, {"title_clean": 1, "original_title": "$title", "message_id": 1, "views_count": 1, "language": 1}).to_list(length=None)
        
        corrected_suggestions = await asyncio.get_event_loop().run_in_executor(
            thread_pool_executor, find_corrected_matches, cleaned_query, all_movie_data, 80, RESULTS_COUNT
        )
        if corrected_suggestions:
            results = corrected_suggestions
            total_count = len(results)
            search_source = f"🤔 আপনি কি **{corrected_suggestions[0]['title']}** খুঁজছেন?"

    return results, total_count, search_source, cleaned_query, tmdb_detected_title

# ==============================================================================
#                           CORE LOGIC: SAVING & BROADCAST
# ==============================================================================

async def process_movie_save(message):
    """
    Parses a message and saves it to the database.
    Ensures 'Same to Same' copy by saving the ID and extracting the Title from the first line.
    Works for both Direct Files and Link Posts (Photos with Captions).
    """
    text = message.caption or message.text
    if not text: 
        return None

    if not (message.photo or message.video or message.document or message.audio):
        return None

    movie_title = text.splitlines()[0].strip()
    
    if len(movie_title) < 2: 
        return None
    
    thumbnail_file_id = None
    if message.photo:
        thumbnail_file_id = message.photo.file_id 
    elif message.video and message.video.thumbs:
        thumbnail_file_id = message.video.thumbs[0].file_id 
    elif message.document and message.document.thumbs:
        thumbnail_file_id = message.document.thumbs[0].file_id

    raw_data = {
        "chat_id": message.chat.id,    # Source Channel ID
        "message_id": message.id,      # Source Message ID
        "title": movie_title,          # Display Title
        "full_caption": text,          # Full Caption
        "date": message.date,
        "year": extract_year(text),    
        "language": extract_language(text), 
        "title_clean": clean_text(text), 
        "views_count": 0,
        "thumbnail_id": thumbnail_file_id 
    }

    try:
        existing = await movies_col.find_one({"chat_id": message.chat.id, "message_id": message.id})
        if not existing:
            validated_data = movie_schema.load(raw_data)
            await movies_col.insert_one(validated_data)
            return movie_title
    except ValidationError as err:
        logger.error(f"Validation Error: {err.messages}")
    except Exception as e:
        logger.error(f"Save Error: {e}")
    
    return None

async def auto_group_messenger():
    """ Sends auto messages to all groups every 20 minutes """
    print("✅ Auto Group Messenger Service Started...")
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
    """ Robust Broadcast Function with Progress Bar (Used for Auto-Notification) """
    success = 0
    failed = 0
    start_time = time.time()
    semaphore = asyncio.Semaphore(20) # Controls concurrency
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
                except:
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
                f"🚀 **Broadcasting...**\n\n"
                f"{progress_bar} **{percentage:.1f}%**\n"
                f"✅ OK: `{success}` | ❌ Fail: `{failed}`\n"
                f"⚡ Speed: `{speed:.1f} u/s`\n"
                f"⏳ ETA: `{get_readable_time(eta)}`"
            )
            try:
                if status_msg:
                    await (status_msg.edit_caption(text) if status_msg.photo else status_msg.edit_text(text))
            except: pass
            
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
    final_text = f"✅ **Broadcast Done!**\nTime: `{get_readable_time(elapsed)}`\nSuccess: {success}\nFailed: {failed}"
    
    if status_msg:
        try:
            await (status_msg.edit_caption(final_text) if status_msg.photo else status_msg.edit_text(final_text))
        except: pass

async def auto_broadcast_worker(movie_title, message_id, thumbnail_id=None):
    """ Automatically notifies all users when a new movie is added """
    download_link = f"https://t.me/{app.me.username}?start=watch_{message_id}"
    
    download_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 ডাউনলোড করতে ক্লিক করুন", url=download_link)]
    ])
    
    notification_caption = f"🎬 **নতুন মুভি আপলোড হয়েছে!**\n\n**{movie_title}**\n\nএখনই নিচের বাটনে ক্লিক করে ডাউনলোড করুন! 👇"
    
    total_users = await users_col.count_documents({"notify": {"$ne": False}})
    if total_users == 0: return

    status_msg = None
    if ADMIN_IDS:
        try:
            pic_to_use = thumbnail_id if thumbnail_id else BROADCAST_PIC
            status_msg = await app.send_photo(ADMIN_IDS[0], photo=pic_to_use, caption=f"🚀 **অটো নোটিফিকেশন শুরু...**\n👥 ইউজার: `{total_users}`")
        except: pass

    async def send_func(user_id):
        if thumbnail_id:
            msg = await app.send_photo(user_id, photo=thumbnail_id, caption=notification_caption, reply_markup=download_button)
        else:
            msg = await app.send_message(user_id, notification_caption, reply_markup=download_button)
        if msg: asyncio.create_task(delete_message_later(msg.chat.id, msg.id, delay=86400))

    cursor = users_col.find({"notify": {"$ne": False}}, {"_id": 1})
    await broadcast_messages(cursor, send_func, status_msg, total_users)

# ==============================================================================
#                           BOT HANDLERS & COMMANDS
# ==============================================================================

# 1. AUTO SAVE FROM PRIMARY CHANNEL
@app.on_message(filters.chat(CHANNEL_ID))
async def save_post(_, msg: Message):
    title = await process_movie_save(msg)
    if title:
        # Check Global Notify Setting
        setting = await settings_col.find_one({"key": "global_notify"})
        if setting and setting.get("value", True):
            thumb = msg.photo.file_id if msg.photo else (msg.video.thumbs[0].file_id if msg.video and msg.video.thumbs else None)
            asyncio.create_task(auto_broadcast_worker(title, msg.id, thumb))

# 2. LOG GROUP ACTIVATION
@app.on_message(filters.group, group=10)
async def log_group(_, msg: Message):
    await groups_col.update_one(
        {"_id": msg.chat.id}, 
        {"$set": {"title": msg.chat.title, "active": True}}, 
        upsert=True
    )

# 3. MANUAL INDEXING COMMAND (For Multi-Channel)
@app.on_message(filters.command("index") & filters.user(ADMIN_IDS))
async def index_channel_handler(_, msg: Message):
    target_chat_id = None
    
    if msg.reply_to_message and msg.reply_to_message.forward_from_chat:
        target_chat_id = msg.reply_to_message.forward_from_chat.id
    elif len(msg.command) > 1:
        try: target_chat_id = int(msg.command[1])
        except: pass

    if not target_chat_id:
        return await msg.reply("❌ চ্যানেল আইডি পাওয়া যায়নি। সঠিক নিয়ম: `/index -100xxxx` অথবা চ্যানেল থেকে ফরোয়ার্ড করা মেসেজে রিপ্লাই দিন।")

    try:
        check_msg = await app.send_message(target_chat_id, "⚠️ **Indexing Logic initialized...**")
        last_msg_id = check_msg.id
        await check_msg.delete()
    except Exception as e:
        return await msg.reply(f"❌ **Error:** বট ওই চ্যানেলে মেসেজ পাঠাতে পারছে না। বটকে অবশ্যই **Admin** হতে হবে।\nError: {e}")

    status_msg = await msg.reply(f"⏳ **Indexing Started...**\n🎯 Target: `{target_chat_id}`\n🔢 Last ID: `{last_msg_id}`\n🚀 Speed: `Safe Mode`")
    
    total_indexed = 0
    total_skipped = 0
    already_exists = 0
    
    batch_size = 100
    
    try:
        for i in range(last_msg_id, 0, -batch_size):
            try:
                start_id = i
                end_id = max(1, i - batch_size + 1)
                ids = list(range(start_id, end_id - 1, -1))
                
                try:
                    messages = await app.get_messages(target_chat_id, ids)
                except FloodWait as e:
                    await asyncio.sleep(e.value + 2) 
                    messages = await app.get_messages(target_chat_id, ids)
                except Exception as e:
                    logger.error(f"Fetch Error: {e}")
                    continue

                if not messages:
                    continue

                for message in messages:
                    if not message or message.empty:
                        continue
                        
                    try:
                        exists = await movies_col.find_one({"chat_id": target_chat_id, "message_id": message.id})
                        if exists:
                            already_exists += 1
                            continue

                        saved_title = await process_movie_save(message)
                        if saved_title: 
                            total_indexed += 1
                        else:
                            total_skipped += 1
                    except Exception as inner_e:
                        logger.error(f"Save Error: {inner_e}")
                
                await asyncio.sleep(1.5)
                
                if i % 200 == 0:
                    try: 
                        await status_msg.edit_text(
                            f"⏳ **Indexing Running...**\n"
                            f"📡 Scanning IDs: {start_id} ➝ {end_id}\n"
                            f"✅ Saved: {total_indexed}\n"
                            f"♻️ Already Exists: {already_exists}\n"
                            f"⏭ Skipped (No Media): {total_skipped}"
                        )
                    except: pass
                    
            except Exception as e:
                logger.error(f"Batch Loop Error: {e}")
                pass

    except Exception as e:
        return await status_msg.edit_text(f"❌ **Critical Error:** {e}")

    await status_msg.edit_text(
        f"✅ **Indexing Completed!**\n"
        f"📂 চ্যানেল: `{target_chat_id}`\n"
        f"💾 নতুন সেভ হয়েছে: **{total_indexed}** টি\n"
        f"♻️ আগে থেকেই ছিল: **{already_exists}** টি\n"
        f"🗑 বাদ দেওয়া হয়েছে: **{total_skipped}** টি"
    )

# 4. START COMMAND (Logic Hub)
user_last_start_time = {}

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
        
        protect_setting = await settings_col.find_one({"key": "protect_content"})
        should_protect = protect_setting.get("value", True) if protect_setting else True
        
        # --- A. VERIFIED LINK HANDLER ---
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
                await msg.reply("⚠️ **ভেরিফিকেশন অসম্পূর্ণ!**", quote=True)
                return

            message_id = verify_data["movie_id"]
            
            # Get Source Chat ID (Fallback to CHANNEL_ID if missing)
            source_chat_id = verify_data.get("chat_id", CHANNEL_ID)

            try:
                await app.copy_message(
                    chat_id=msg.chat.id,        
                    from_chat_id=source_chat_id,    
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
                
            except Exception as e:
                await msg.reply(f"❌ মুভিটি খুঁজে পাওয়া যাচ্ছে না। Error: {e}")
            return
            
        # --- B. DIRECT/NOTIFICATION LINK HANDLER ---
        elif argument.startswith("watch_"):
            message_id = int(argument.replace("watch_", ""))
            
            movie = await movies_col.find_one({"message_id": message_id})
            source_chat_id = movie["chat_id"] if movie else CHANNEL_ID

            verify_setting = await settings_col.find_one({"key": "verification_mode"})
            is_verify_on = verify_setting.get("value", True) if verify_setting else True
            
            if is_verify_on:
                verify_link = await create_verification_link(message_id, user_id)
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Verify to Download (Free)", url=verify_link)]])
                await msg.reply(
                    "🔒 **ফাইলটি লক করা আছে!**\n\nফাইলটি পেতে নিচের বাটনে ক্লিক করে ভেরিফিকেশন সম্পন্ন করুন। এটি সম্পূর্ণ ফ্রি।",
                    reply_markup=btn,
                    quote=True
                )
                return
            
            try:
                await app.copy_message(
                    chat_id=msg.chat.id,
                    from_chat_id=source_chat_id,
                    message_id=message_id,
                    protect_content=should_protect
                )
                await movies_col.update_one({"message_id": message_id}, {"$inc": {"views_count": 1}})
            except:
                await msg.reply("❌ ফাইলটি পাওয়া যাচ্ছে না।")
            return

    # Normal Welcome Message
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

# ------------------- ADMIN COMMANDS -------------------

# Protect Content Toggle
@app.on_message(filters.command("protect") & filters.user(ADMIN_IDS))
async def toggle_protection(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        await msg.reply("ব্যবহার:\n`/protect on` - ফরোয়ার্ড বন্ধ\n`/protect off` - ফরোয়ার্ড চালু")
        return
    
    new_status = True if msg.command[1] == "on" else False
    await settings_col.update_one({"key": "protect_content"}, {"$set": {"value": new_status}}, upsert=True)
    await msg.reply(f"🔒 **ফাইল প্রোটেকশন {'চালু' if new_status else 'বন্ধ'} করা হয়েছে!**")

# Verify Mode Toggle
@app.on_message(filters.command("verify") & filters.user(ADMIN_IDS))
async def toggle_verification(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        await msg.reply("ব্যবহার:\n`/verify on` - ওয়েবসাইট ভেরিফিকেশন চালু\n`/verify off` - ডাইরেক্ট ফাইল")
        return
    
    new_status = True if msg.command[1] == "on" else False
    await settings_col.update_one({"key": "verification_mode"}, {"$set": {"value": new_status}}, upsert=True)
    await msg.reply(f"🌍 **ভেরিফিকেশন মোড {'চালু' if new_status else 'বন্ধ'} করা হয়েছে!**")

# ==============================================================================
#                           UPDATED BROADCAST HANDLER
# ==============================================================================
# এই অংশটি আপনার চাহিদা অনুযায়ী আপডেট করা হয়েছে।
# এটি কোনো মেসেজে রিপ্লাই দিয়ে /broadcast কমান্ড দিলে কাজ করবে।

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS) & filters.reply)
async def broadcast_handler(bot, m):
    # শুরুর সময় এবং স্ট্যাটাস মেসেজ
    start_time = time.time()
    status_msg = await m.reply_text("📢 **ব্রডকাস্ট শুরু হচ্ছে...**\nদয়া করে অপেক্ষা করুন।", quote=True)
    
    # যে মেসেজটি পাঠাতে হবে
    broadcast_msg = m.reply_to_message
    
    # ডাটাবেস থেকে সব ইউজার নেওয়া
    total_users = await users_col.count_documents({})
    all_users = users_col.find({})
    
    done = 0
    blocked = 0
    deleted = 0
    failed = 0
    
    async for user in all_users:
        user_id = user.get("_id")
        
        try:
            # মেসেজটি কপি করে পাঠানো (Forward Tag ছাড়া)
            await broadcast_msg.copy(chat_id=user_id)
            done += 1
            
        except FloodWait as e:
            # টেলিগ্রাম লিমিট দিলে অপেক্ষা করবে
            await asyncio.sleep(e.value)
            try:
                await broadcast_msg.copy(chat_id=user_id)
                done += 1
            except Exception:
                failed += 1
                
        except UserIsBlocked:
            # ইউজার যদি বট ব্লক করে রাখে
            blocked += 1
            
        except InputUserDeactivated:
            # ইউজার যদি একাউন্ট ডিলিট করে দেয়
            deleted += 1
            await users_col.delete_one({"_id": user_id})
            
        except Exception:
            failed += 1
            
        # প্রতি ২০ জন পর পর স্ট্যাটাস আপডেট করবে
        if done % 20 == 0:
            await status_msg.edit_text(
                f"📢 **ব্রডকাস্ট চলছে...**\n\n"
                f"✅ সফল: `{done}`\n"
                f"❌ ব্লকড: `{blocked}`\n"
                f"🗑 ডিলিটেড: `{deleted}`\n"
                f"⚠️ ফেইলড: `{failed}`\n"
                f"👥 মোট ইউজার: `{total_users}`"
            )

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    
    # শেষ হলে ফাইনাল রিপোর্ট
    await status_msg.edit_text(
        f"✅ **ব্রডকাস্ট সম্পন্ন হয়েছে!**\n\n"
        f"✅ সফলভাবে পাঠানো হয়েছে: `{done}` জন\n"
        f"❌ ইউজার ব্লক করেছে: `{blocked}` জন\n"
        f"🗑 ডিলিটেড একাউন্ট: `{deleted}` জন\n"
        f"⚠️ ফেইলড: `{failed}` জন\n\n"
        f"⏳ সময় লেগেছে: `{time_taken}`"
    )

# Stats Command
@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg: Message):
    total_groups = await groups_col.count_documents({})
    total_users = await users_col.count_documents({})
    total_movies = await movies_col.count_documents({})
    
    stats_msg = await msg.reply(
        f"📊 **Bot Statistics**\n\n"
        f"👤 Users: {total_users}\n"
        f"👥 Groups: {total_groups}\n"
        f"🎬 Movies: {total_movies}"
    )
    asyncio.create_task(delete_message_later(stats_msg.chat.id, stats_msg.id))

# Notify Toggle
@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify_command(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        await msg.reply("ব্যবহার: /notify on অথবা /notify off")
        return
    new_value = True if msg.command[1] == "on" else False
    await settings_col.update_one({"key": "global_notify"}, {"$set": {"value": new_value}}, upsert=True)
    await msg.reply(f"✅ গ্লোবাল নোটিফিকেশন {'চালু' if new_value else 'বন্ধ'} করা হয়েছে!")

# Feedback
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

# ------------------- SAFE: Bulk Delete Feature (With Preview) -------------------
@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_specific_movie(_, msg: Message):
    if len(msg.command) < 2:
        await msg.reply("টাইটেল দিন। ব্যবহার: `/delete_movie <নাম>`")
        return
    title = msg.text.split(None, 1)[1].strip()
    
    matches = await movies_col.find({"title": {"$regex": re.escape(title), "$options": "i"}}).to_list(length=100)
    
    if not matches:
        await msg.reply(f"❌ **'{title}'** নামে কোনো ফাইল পাওয়া যায়নি।")
        return

    text = f"⚠️ **সতর্কতা! আপনি নিচের ফাইলগুলো ডিলিট করতে যাচ্ছেন:**\n\n"
    for idx, movie in enumerate(matches[:15], 1): 
        text += f"{idx}. {movie['title']}\n"
    
    if len(matches) > 15:
        text += f"\n... এবং আরও {len(matches) - 15} টি ফাইল।"
        
    text += f"\n\n🔥 **মোট ফাইল:** {len(matches)} টি\nআপনি কি নিশ্চিত যে আপনি এগুলো সব ডিলিট করতে চান?"
    
    encoded_title = urllib.parse.quote_plus(title)
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ হ্যাঁ, সব ডিলিট করুন", callback_data=f"confirm_del_{encoded_title}")],
        [InlineKeyboardButton("❌ না, বাতিল করুন", callback_data="cancel_del")]
    ])
    
    await msg.reply(text, reply_markup=btn)

@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies_command(_, msg: Message):
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("হ্যাঁ, সব ডিলিট করুন", callback_data="confirm_delete_all_movies")],
        [InlineKeyboardButton("না, বাতিল করুন", callback_data="cancel_delete_all_movies")]
    ])
    await msg.reply("সব মুভি ডিলিট করতে চান? এটি অপরিবর্তনীয়!", reply_markup=btn)

# ------------------- REQUEST SYSTEM -------------------
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

# ------------------- SMART SEARCH HANDLER -------------------

@app.on_message(filters.text & ~filters.command(["start", "index", "delete_movie", "delete_all_movies", "protect", "verify", "broadcast", "notify", "stats", "feedback", "request"]) & (filters.group | filters.private))
async def search(_, msg: Message):
    query = msg.text.strip()
    if not query: return
    
    if msg.chat.type in ["group", "supergroup"]:
        await groups_col.update_one({"_id": msg.chat.id}, {"$set": {"title": msg.chat.title, "active": True}}, upsert=True)
        # Filters for Groups
        if len(query) < 2 or msg.reply_to_message or msg.from_user.is_bot: return
        if query.startswith("/"): return

    user_id = msg.from_user.id
    
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"last_query": query}, "$setOnInsert": {"joined": datetime.now(timezone.utc)}},
        upsert=True
    )

    loading_message = await msg.reply("🔎 <b>Searching...</b>", quote=True)
    
    results, total_count, search_source, cleaned_query, tmdb_detected_title = await get_search_results(query, offset=0)

    if results:
        await loading_message.delete()
        header_text = f"🎬 **আপনার মুভি পাওয়া গেছে:**\n{search_source}" if search_source else "🎬 **আপনার মুভি পাওয়া গেছে:**"
        
        await send_results(msg, results, total_count, offset=0, header=header_text, from_callback=False)
        return

    await loading_message.delete()
    final_query = tmdb_detected_title if tmdb_detected_title else cleaned_query
    encoded_final_query = urllib.parse.quote_plus(final_query)
    Google_Search_url = "https://www.google.com/search?q=" + urllib.parse.quote(final_query)
    
    req_btn = InlineKeyboardButton(f"✅ রিকোয়েস্ট করুন", callback_data=f"request_movie_{user_id}_{encoded_final_query}")
    google_btn = InlineKeyboardButton("🌐 গুগলে দেখুন", url=Google_Search_url)
    
    alert_text = (
        f"❌ **'{query}'** পাওয়া যায়নি।\n"
        f"💡 **আপনি কি এটি খুঁজছিলেন?** 👉 **{tmdb_detected_title}**\n\n"
        f"রিকোয়েস্ট করতে নিচের বাটনে ক্লিক করুন。"
    ) if tmdb_detected_title else f"❌ দুঃখিত! **'{cleaned_query}'** পাওয়া যায়নি。"

    alert = await msg.reply_text(alert_text, reply_markup=InlineKeyboardMarkup([[req_btn], [google_btn]]), quote=True)
    asyncio.create_task(delete_message_later(alert.chat.id, alert.id))

    encoded_query_admin = urllib.parse.quote_plus(query)
    admin_btns = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 Uploading", callback_data=f"rep_uploading_{user_id}_{encoded_query_admin}"),
            InlineKeyboardButton("✅ Uploaded", callback_data=f"rep_uploaded_{user_id}_{encoded_query_admin}")
        ],
        [
            InlineKeyboardButton("❌ Unavailable", callback_data=f"rep_unavailable_{user_id}_{encoded_query_admin}"),
            InlineKeyboardButton("⚠️ Spelling Error", callback_data=f"rep_spelling_{user_id}_{encoded_query_admin}")
        ],
        [
            InlineKeyboardButton("🗑 Delete Msg", callback_data=f"rep_delete_{user_id}_{encoded_query_admin}")
        ]
    ])

    user_mention = msg.from_user.mention
    admin_msg = (
        f"⚠️ **MISSING FILE ALERT** (Auto)\n\n"
        f"👤 User: {user_mention} (`{user_id}`)\n"
        f"🔍 Search: `{query}`\n\n"
        f"ইউজার মুভিটি খুঁজে পায়নি। আপনি চাইলে এখনই আপলোড করে নিচের বাটন দিয়ে জানাতে পারেন।"
    )

    for admin_id in ADMIN_IDS:
        try:
            await app.send_message(admin_id, admin_msg, reply_markup=admin_btns)
        except Exception:
            pass

async def send_results(msg, results, total_count, offset=0, header="🎬 আপনার মুভি পাওয়া গেছে:", from_callback=False):
    """ Fixed Function: Handles buttons and correct pagination editing """
    
    setting = await settings_col.find_one({"key": "verification_mode"})
    is_verify_on = setting.get("value", True) if setting else True
    
    buttons = []
    user_id = msg.chat.id
    if msg.from_user:
        user_id = msg.from_user.id

    for movie in results:
        title = movie.get('title') or movie.get('original_title')
        mid = movie['message_id']
        
        if is_verify_on:
            link = await create_verification_link(mid, user_id)
        else:
            bot_username = app.me.username
            link = f"https://t.me/{bot_username}?start=watch_{mid}"
        
        buttons.append([
            InlineKeyboardButton(
                text=f"{title[:35]}...",
                url=link
            )
        ])

    buttons.append([
        InlineKeyboardButton("QUALITY", callback_data="filter_quality"),
        InlineKeyboardButton("LANGUAGE", callback_data="filter_lang"),
        InlineKeyboardButton("SEASON", callback_data="filter_season")
    ])

    pagination_buttons = []
    current_page = (offset // RESULTS_COUNT) + 1
    total_pages = math.ceil(total_count / RESULTS_COUNT)
    
    if offset > 0:
        pagination_buttons.append(InlineKeyboardButton("< Back", callback_data=f"prev_page_{offset}"))
    else:
        pagination_buttons.append(InlineKeyboardButton("PAGE", callback_data="ignore"))

    pagination_buttons.append(InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="ignore"))

    if (offset + RESULTS_COUNT) < total_count:
        pagination_buttons.append(InlineKeyboardButton("NEXT >", callback_data=f"next_page_{offset}"))
    else:
        pagination_buttons.append(InlineKeyboardButton("END", callback_data="ignore"))

    buttons.append(pagination_buttons)

    footer = "👇 নিচের লিংকে ক্লিক করে ভেরিফাই করুন:" if is_verify_on else "👇 ডাউনলোড করতে ক্লিক করুন:"
    final_text = f"{header}\n{footer}"
    
    try:
        # FIX: If it is a callback (editing), use edit_text. Else reply.
        if from_callback:
             await msg.edit_text(final_text, reply_markup=InlineKeyboardMarkup(buttons))
        else:
             m = await msg.reply(final_text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
             asyncio.create_task(delete_message_later(m.chat.id, m.id))
    except Exception as e:
        logger.error(f"Send Results Error: {e}")

# ==============================================================================
#                           CALLBACK HANDLER
# ==============================================================================

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data
    user_id = cq.from_user.id
    
    try:
        if data == "home_menu":
            btns = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔰 ADD ME TO YOUR GROUP 🔰", url=f"https://t.me/{app.me.username}?startgroup=true")],
                [
                    InlineKeyboardButton("HELP 📢", callback_data="help_menu"),
                    InlineKeyboardButton("ABOUT 📘", callback_data="about_menu")
                ],
                [
                    InlineKeyboardButton("TOP SEARCHING ⭐", callback_data="top_searching"),
                    InlineKeyboardButton("UPGRADE 🎟️", url=UPDATE_CHANNEL)
                ]
            ])
            await cq.message.edit_caption(
                caption=f"HEY {cq.from_user.mention}, {get_greeting()}\n\n🤖 **I AM {app.me.first_name},** THE MOST\nPOWERFUL AUTO FILTER BOT WITH \nWEB VERIFICATION SYSTEM.",
                reply_markup=btns
            )
        
        elif data == "help_menu":
            help_text = """
**📢 HELP MENU**

1. **Search:** Just type the movie name.
2. **Request:** If not found, click 'Request'.
3. **Verify:** Complete 2 steps to get file (if ads on).
4. **Commands:**
   /start - Check bot status
   /stats - Admin only stats
   /request <name> - Manual request
"""
            await cq.message.edit_caption(caption=help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="home_menu")]]))
        
        elif data == "about_menu":
            about_text = f"""
**📘 ABOUT BOT**

🤖 **Name:** {app.me.first_name}
🛠 **Language:** Python 3
📚 **Library:** Pyrogram & Motor
📡 **Server:** Koyeb / VPS
👨‍💻 **Developer:** Ctgmovies23
"""
            await cq.message.edit_caption(caption=about_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="home_menu")]]))

        elif data == "top_searching":
            top_movies = await movies_col.find().sort("views_count", -1).limit(10).to_list(length=10)
            
            if not top_movies:
                await cq.answer("⚠️ No popular movies found yet!", show_alert=True)
                return
            
            msg_text = "⭐ **TOP 10 MOST SEARCHED MOVIES:**\n\n"
            buttons = []
            setting = await settings_col.find_one({"key": "verification_mode"})
            is_verify_on = setting.get("value", True) if setting else True

            for idx, movie in enumerate(top_movies, 1):
                title = movie.get('title', 'Unknown')
                mid = movie['message_id']
                views = movie.get('views_count', 0)
                
                link = await create_verification_link(mid, user_id) if is_verify_on else f"https://t.me/{app.me.username}?start=watch_{mid}"
                
                msg_text += f"{idx}. {title} ({views} views)\n"
                buttons.append([InlineKeyboardButton(f"{idx}. {title}", url=link)])
            
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="home_menu")])
            
            await cq.message.edit_caption(caption=msg_text, reply_markup=InlineKeyboardMarkup(buttons))

        # --- FIX: PAGINATION HANDLER (IN-PLACE EDIT) ---
        elif data.startswith("next_page_") or data.startswith("prev_page_"):
            user_data = await users_col.find_one({"_id": user_id})
            if not user_data or "last_query" not in user_data:
                await cq.answer("⚠️ সেশন এক্সপায়ার হয়েছে। আবার সার্চ করুন।", show_alert=True)
                return
            
            last_query = user_data["last_query"]
            current_offset = int(data.split("_")[2])
            
            if "next" in data:
                new_offset = current_offset + RESULTS_COUNT
            else:
                new_offset = max(0, current_offset - RESULTS_COUNT)
            
            results, total_count, _, _, _ = await get_search_results(last_query, offset=new_offset)
            
            if results:
                # IMPORTANT: from_callback=True ensures editing
                await send_results(cq.message, results, total_count, offset=new_offset, header=f"🔎 ফলাফল: **{last_query}**", from_callback=True)
            else:
                await cq.answer("⚠️ আর কোনো ফলাফল নেই!", show_alert=True)

        # --- FIX: WORKING FILTERS (Quality, Language, Season) ---
        elif data == "filter_quality":
            buttons = [
                [InlineKeyboardButton("480p", callback_data="add_filter_480p"), InlineKeyboardButton("720p", callback_data="add_filter_720p")],
                [InlineKeyboardButton("1080p", callback_data="add_filter_1080p"), InlineKeyboardButton("4K / 2160p", callback_data="add_filter_4k")],
                [InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_search")]
            ]
            await cq.message.edit_text("🎥 **Select Quality:**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "filter_lang":
            buttons = [
                [InlineKeyboardButton("Hindi", callback_data="add_filter_Hindi"), InlineKeyboardButton("Bengali", callback_data="add_filter_Bengali")],
                [InlineKeyboardButton("English", callback_data="add_filter_English"), InlineKeyboardButton("Tamil", callback_data="add_filter_Tamil")],
                [InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_search")]
            ]
            await cq.message.edit_text("🗣 **Select Language:**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "filter_season":
            buttons = [
                [InlineKeyboardButton("Season 1", callback_data="add_filter_S01"), InlineKeyboardButton("Season 2", callback_data="add_filter_S02")],
                [InlineKeyboardButton("Season 3", callback_data="add_filter_S03"), InlineKeyboardButton("Season 4", callback_data="add_filter_S04")],
                [InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_search")]
            ]
            await cq.message.edit_text("📺 **Select Season:**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("add_filter_"):
            # Logic: Get last query, Append new filter, Save, Search again
            filter_text = data.split("_")[2]
            user_data = await users_col.find_one({"_id": user_id})
            
            if user_data and "last_query" in user_data:
                old_query = user_data["last_query"]
                # Append filter text to query (e.g. "Avengers" -> "Avengers 720p")
                new_query = f"{old_query} {filter_text}".strip()
                
                await users_col.update_one({"_id": user_id}, {"$set": {"last_query": new_query}})
                
                # Run search with new query
                results, total_count, _, _, _ = await get_search_results(new_query, offset=0)
                
                if results:
                    await send_results(cq.message, results, total_count, offset=0, header=f"🔎 ফিল্টার করা হয়েছে: **{new_query}**", from_callback=True)
                else:
                    await cq.answer("⚠️ এই ফিল্টারে কোনো ফাইল পাওয়া যায়নি!", show_alert=True)
                    # Go back to original results
                    await users_col.update_one({"_id": user_id}, {"$set": {"last_query": old_query}})
            else:
                await cq.answer("⚠️ সেশন টাইমআউট! আবার সার্চ করুন।", show_alert=True)

        elif data == "back_to_search":
            user_data = await users_col.find_one({"_id": user_id})
            if user_data and "last_query" in user_data:
                results, total_count, _, _, _ = await get_search_results(user_data["last_query"], offset=0)
                await send_results(cq.message, results, total_count, offset=0, header=f"🔎 ফলাফল: **{user_data['last_query']}**", from_callback=True)
            else:
                await cq.answer("Expired!", show_alert=True)

        elif data == "ignore":
            await cq.answer()

        elif data.startswith("report_"):
            await cq.answer("Report Sent!", show_alert=True)
        
        elif data.startswith("confirm_del_"):
            try:
                title_encoded = data.replace("confirm_del_", "")
                title = urllib.parse.unquote_plus(title_encoded)
                result = await movies_col.delete_many({"title": {"$regex": re.escape(title), "$options": "i"}})
                await cq.message.edit_text(f"✅ **সফল!**\n**'{title}'** সম্পর্কিত মোট **{result.deleted_count}** টি ফাইল ডিলিট করা হয়েছে।")
            except Exception as e:
                await cq.message.edit_text(f"❌ এরর: {e}")

        elif data == "cancel_del":
            await cq.message.edit_text("❌ ডিলিট বাতিল করা হয়েছে।")
            
        elif data == "confirm_delete_all_movies":
            await movies_col.delete_many({})
            await cq.message.edit_text("✅ All Deleted!")

        elif data == "cancel_delete_all_movies":
            await cq.message.edit_text("❌ Cancelled!")

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
                    f"🔔 **নতুন মুভি রিকোয়েস্ট!** (Manual)\n\n"
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

    except MessageNotModified:
        await cq.answer("Already on this page!")
    except Exception as e:
        logger.error(f"Callback Error: {e}")

if __name__ == "__main__":
    print("🚀 Bot Started (Ultimate Version with Pagination & Filters)...")
    Thread(target=run_flask).start() # Start Flask Web Server
    app.loop.create_task(init_settings()) # Init Settings
    app.loop.create_task(auto_group_messenger()) # Start Auto Msg
    app.run() # Start Bot
