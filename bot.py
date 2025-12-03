#
# ----------------------------------------------------
# Developed by: Ctgmovies23
# Final Fix: Smart Auto-Correction + DB Re-Search Logic
# Status: 100% Verified & Ready
# ----------------------------------------------------
#

import os
import re
import time
import math
import asyncio
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

# ------------------- লাইব্রেরি ইম্পোর্ট -------------------
import ujson  # Fast JSON
import aiohttp # For Async Web Requests (BS4 & TMDB)
from bs4 import BeautifulSoup # For Google Spell Check
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
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/TGLinkBase")
TMDB_API_KEY = os.getenv("TMDB_API_KEY") # TMDB API Key
START_PIC = os.getenv("START_PIC", "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg")
BROADCAST_PIC = os.getenv("BROADCAST_PIC", "https://telegra.ph/file/18659550b694b47000787.jpg")

# [CONFIG] অটো মেসেজ সেটিংস
AUTO_MSG_INTERVAL = 250  
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

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- MongoDB (Async Motor) & Schema -------------------
motor_client = AsyncIOMotorClient(DATABASE_URL)
db = motor_client["movie_bot"]

movies_col = db["movies"]
users_col = db["users"]
groups_col = db["groups"]
settings_col = db["settings"]
requests_col = db["requests"]
feedback_col = db["feedback"]

# Sync Client (ইনডেক্স তৈরির জন্য)
try:
    sync_client = MongoClient(DATABASE_URL)
    sync_db = sync_client["movie_bot"]
    sync_db.movies.create_index("message_id", unique=True, background=True)
    sync_db.movies.create_index([("title_clean", ASCENDING)], background=True)
    sync_db.movies.create_index("language", background=True)
    sync_db.movies.create_index([("views_count", ASCENDING)], background=True)
    print("✅ Database Indexes Created Successfully!")
except Exception as e:
    print(f"⚠️ Index Error: {e}")

# Marshmallow Schema
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
    await settings_col.update_one(
        {"key": "protect_forwarding"},
        {"$setOnInsert": {"value": True}},
        upsert=True
    )

# ------------------- Flask অ্যাপ -------------------
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Advanced Bot is running with Motor, BS4 & TMDB!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start() 

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

# ------------------- সিস্টেম ইঞ্জিন -------------------
async def auto_group_messenger():
    print("✅ অটো গ্রুপ মেসেজ সিস্টেম চালু হয়েছে (Async)...")
    while True:
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
        await asyncio.sleep(AUTO_MSG_INTERVAL)

async def broadcast_messages(user_ids, message_func, status_msg=None, total_users=0):
    success = 0
    failed = 0
    start_time = time.time()
    sem = asyncio.Semaphore(20) 

    async def send_worker(user_id):
        nonlocal success, failed
        async with sem:
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
            if done >= total_users:
                break
            if status_msg:
                elapsed = time.time() - start_time
                if elapsed == 0: elapsed = 1
                percentage = (done / total_users) * 100
                progress_bar = f"[{'■' * int(percentage // 10)}{'□' * (10 - int(percentage // 10))}]"
                text = (
                    f"🚀 **ব্রডকাস্ট চলছে...**\n\n"
                    f"{progress_bar} **{percentage:.1f}%**\n"
                    f"✅ সফল: `{success}` | ❌ ব্যর্থ: `{failed}`\n"
                    f"⏱ সময়: `{get_readable_time(elapsed)}`"
                )
                try:
                    await (status_msg.edit_caption(text) if status_msg.photo else status_msg.edit_text(text))
                except Exception: pass

    updater_task = asyncio.create_task(update_status_loop())
    await asyncio.gather(*[send_worker(uid) for uid in user_ids])
    updater_task.cancel()

    elapsed = time.time() - start_time
    final_text = f"✅ **ব্রডকাস্ট সম্পন্ন!**\n✅ সফল: `{success}`\n❌ ব্যর্থ: `{failed}`\n⏱ সময়: `{get_readable_time(elapsed)}`"
    
    if status_msg:
        try:
            await (status_msg.edit_caption(final_text) if status_msg.photo else status_msg.edit_text(final_text))
        except: pass

async def auto_broadcast_worker(movie_title, message_id, thumbnail_id=None):
    download_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("ডাউনলোড লিংক", url=f"https://t.me/{app.me.username}?start=watch_{message_id}")]
    ])
    notification_caption = f"🎬 **নতুন মুভি আপলোড হয়েছে!**\n\n**{movie_title}**\n\nএখনই ডাউনলোড করুন!"
    
    all_user_ids = [user["_id"] async for user in users_col.find({"notify": {"$ne": False}}, {"_id": 1})]
    total_users = len(all_user_ids)
    if total_users == 0: return

    status_msg = None
    for admin_id in ADMIN_IDS:
        try:
            pic_to_use = thumbnail_id if thumbnail_id else BROADCAST_PIC
            status_msg = await app.send_photo(admin_id, photo=pic_to_use, caption=f"🚀 **অটো নোটিফিকেশন শুরু...**\n👥 ইউজার: `{total_users}`")
            break
        except Exception:
            try:
                status_msg = await app.send_message(admin_id, f"🚀 **অটো নোটিফিকেশন শুরু...**\n👥 ইউজার: `{total_users}`")
                break
            except: pass

    async def send_func(user_id):
        if thumbnail_id:
            msg = await app.send_photo(user_id, photo=thumbnail_id, caption=notification_caption, reply_markup=download_button)
        else:
            msg = await app.send_message(user_id, notification_caption, reply_markup=download_button)
        if msg: asyncio.create_task(delete_message_later(msg.chat.id, msg.id, delay=86400))

    await broadcast_messages(all_user_ids, send_func, status_msg, total_users)

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

    if len(msg.command) > 1 and msg.command[1].startswith("watch_"):
        message_id = int(msg.command[1].replace("watch_", ""))
        protect_setting = await settings_col.find_one({"key": "protect_forwarding"})
        should_protect = protect_setting.get("value", True) if protect_setting else True
        
        try:
            copied_message = await app.copy_message(
                chat_id=msg.chat.id,        
                from_chat_id=CHANNEL_ID,    
                message_id=message_id,      
                protect_content=should_protect 
            )
            movie_data = await movies_col.find_one({"message_id": message_id})
            
            if movie_data:
                action_buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚠️ রিপোর্ট / সমস্যা (Report)", callback_data=f"report_{message_id}")]
                ])
                report_message = await app.send_message(
                    chat_id=msg.chat.id,
                    text="লিংক কাজ না করলে নিচের বাটনে রিপোর্ট করুন:",
                    reply_markup=action_buttons,
                    reply_to_message_id=copied_message.id 
                )
                asyncio.create_task(delete_message_later(report_message.chat.id, report_message.id))
                asyncio.create_task(delete_message_later(copied_message.chat.id, copied_message.id))
            
            await movies_col.update_one({"message_id": message_id}, {"$inc": {"views_count": 1}})
            
        except Exception:
            error_msg = await msg.reply_text("মুভিটি খুঁজে পাওয়া যায়নি বা লোড করা যায়নি।")
            asyncio.create_task(delete_message_later(error_msg.chat.id, error_msg.id))
        return 

    await users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"joined": datetime.now(timezone.utc), "notify": True}},
        upsert=True
    )

    greeting = get_greeting()
    user_mention = msg.from_user.mention
    bot_username = app.me.username
    
    start_caption = f"""
HEY {user_mention}, {greeting}

🤖 **I AM {app.me.first_name},** THE MOST
POWERFUL AUTO FILTER BOT WITH 
PREMIUM FEATURES.
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

# ------------------- অ্যাডমিন কমান্ড ও অন্যান্য কমান্ড (সার্চের আগে রাখা হয়েছে) -------------------

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg: Message):
    if not msg.reply_to_message and len(msg.command) < 2:
        await msg.reply("ব্যবহার:\n১. কোনো মেসেজে রিপ্লাই দিয়ে `/broadcast` লিখুন।\n২. অথবা `/broadcast আপনার মেসেজ` লিখুন।")
        return
    
    all_user_ids = [user["_id"] async for user in users_col.find({}, {"_id": 1})]
    total_users = len(all_user_ids)
    
    if total_users == 0:
        await msg.reply("ডাটাবেসে কোনো ইউজার নেই।")
        return
        
    status_msg = await msg.reply_photo(photo=BROADCAST_PIC, caption=f"🚀 **ম্যানুয়াল ব্রডকাস্ট শুরু...**\n👥 টার্গেট: `{total_users}`")
    
    async def send_func(user_id):
        if msg.reply_to_message:
            await msg.reply_to_message.copy(user_id)
        else:
            broadcast_text = msg.text.split(None, 1)[1]
            await app.send_message(user_id, broadcast_text, disable_web_page_preview=True)

    await broadcast_messages(all_user_ids, send_func, status_msg, total_users)

@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg: Message):
    if len(msg.command) < 2:
        error_msg = await msg.reply("অনুগ্রহ করে /feedback এর পর আপনার মতামত লিখুন।")
        asyncio.create_task(delete_message_later(error_msg.chat.id, error_msg.id))
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
        f"""মোট ব্যবহারকারী: {total_users}
মোট গ্রুপ: {total_groups}
মোট মুভি: {total_movies}
মোট ফিডব্যাক: {total_feedback}
মোট অনুরোধ: {total_requests}"""
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

@app.on_message(filters.command("forward_toggle") & filters.user(ADMIN_IDS))
async def toggle_forward_protection(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        await msg.reply("ব্যবহার: /forward_toggle on (বন্ধ) / off (চালু)")
        return
    new_value = True if msg.command[1] == "on" else False
    await settings_col.update_one({"key": "protect_forwarding"}, {"$set": {"value": new_value}}, upsert=True)
    status = "বন্ধ" if new_value else "চালু"
    await msg.reply(f"✅ ফরওয়ার্ডিং {status} করা হয়েছে!")

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_specific_movie(_, msg: Message):
    if len(msg.command) < 2:
        await msg.reply("টাইটেল দিন। ব্যবহার: `/delete_movie <নাম>`")
        return
    title = msg.text.split(None, 1)[1].strip()
    
    movie = await movies_col.find_one({"title": {"$regex": re.escape(title), "$options": "i"}})
    if not movie:
        movie = await movies_col.find_one({"title_clean": {"$regex": clean_text(title), "$options": "i"}})
    
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

@app.on_message(filters.command("popular") & (filters.private | filters.group))
async def popular_movies(_, msg: Message):
    cursor = movies_col.find({"views_count": {"$exists": True}}).sort("_count", -1).limit(RESULTS_COUNT)
    popular_movies_list = await cursor.to_list(length=RESULTS_COUNT)

    if popular_movies_list:
        buttons = []
        for movie in popular_movies_list:
            if "title" in movie and "message_id" in movie:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"{movie['title'][:40]} ({movie.get('views_count', 0)} ভিউ)",
                        url=f"https://t.me/{app.me.username}?start=watch_{movie['message_id']}"
                    )
                ])
        m = await msg.reply_text("🔥 **জনপ্রিয় মুভিগুলো:**\n\n", reply_markup=InlineKeyboardMarkup(buttons), quote=True)
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
    else:
        await msg.reply_text("কোনো জনপ্রিয় মুভি পাওয়া যায়নি।", quote=True)

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

# ------------------- স্মার্ট সার্চ হ্যান্ডলার (কমান্ডের নিচে) -------------------

@app.on_message(filters.text & ~filters.command(["start", "broadcast", "stats", "feedback", "request", "popular", "notify", "delete_movie", "delete_all_movies", "forward_toggle"]) & (filters.group | filters.private))
async def search(_, msg: Message):
    query = msg.text.strip()
    if not query: return
    
    # গ্রুপ আপডেট
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
    
    # প্রসেসিং
    raw_year = extract_year(query)
    cleaned_query = smart_search_clean(query)
    if not cleaned_query: cleaned_query = query.lower()

    search_source = ""
    results = []
    
    # Priority 1: Exact / Word Boundary
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

    # Priority 2: Loose Match (if no year)
    if not results and not raw_year:
        loose_pattern = re.escape(cleaned_query)
        db_cursor = movies_col.find({
            "title_clean": {"$regex": loose_pattern, "$options": "i"}
        }).sort("views_count", -1).limit(RESULTS_COUNT)
        results = await db_cursor.to_list(length=RESULTS_COUNT)

    # -------------------------------------------------------------------------
    # Priority 3: TMDB Search & Auto-Fix Logic (UPDATED)
    # -------------------------------------------------------------------------
    tmdb_detected_title = None
    if not results:
        # ১. আগে TMDB থেকে সঠিক নামটা আনবো
        tmdb_detected_title = await get_tmdb_suggestion(cleaned_query)
        
        if tmdb_detected_title:
            tmdb_clean = clean_text(tmdb_detected_title)
            
            # ২. প্রথমে একটু লুজ (Loose) সার্চ করবো ফিক্স করা নাম দিয়ে
            db_cursor = movies_col.find({
                "$or": [
                    {"title_clean": {"$regex": re.escape(tmdb_clean), "$options": "i"}},
                    {"title": {"$regex": re.escape(tmdb_detected_title), "$options": "i"}}
                ]
            }).sort("views_count", -1).limit(RESULTS_COUNT)
            
            results = await db_cursor.to_list(length=RESULTS_COUNT)
            
            if results:
                search_source = f"✅ **Auto Corrected:** '{tmdb_detected_title}'"
            
            # ৩. যদি লুজ সার্চেও না পায়, তাহলে ফিক্স করা নাম দিয়েই Fuzzy Search চালাবো
            else:
                all_movie_data = await movies_col.find({}, {"title_clean": 1, "original_title": "$title", "message_id": 1, "views_count": 1}).to_list(length=None)
                tmdb_fuzzy_results = await asyncio.get_event_loop().run_in_executor(
                    thread_pool_executor, find_corrected_matches, tmdb_clean, all_movie_data, 80, RESULTS_COUNT
                )
                if tmdb_fuzzy_results:
                    results = tmdb_fuzzy_results
                    search_source = f"✅ **Auto Corrected:** '{tmdb_detected_title}'"

    # Priority 4: Fuzzy Logic (User input দিয়ে শেষ চেষ্টা)
    if not results and not raw_year and not tmdb_detected_title:
        all_movie_data = await movies_col.find({}, {"title_clean": 1, "original_title": "$title", "message_id": 1, "views_count": 1}).to_list(length=None)
        corrected_suggestions = await asyncio.get_event_loop().run_in_executor(
            thread_pool_executor, find_corrected_matches, cleaned_query, all_movie_data, 80, RESULTS_COUNT
        )

        if corrected_suggestions:
            results = corrected_suggestions
            search_source = f"🤔 আপনি কি **{corrected_suggestions[0]['title']}** খুঁজছেন?"

    # ফলাফল প্রদান (Results Found)
    if results:
        await loading_message.delete()
        header_text = f"🎬 **আপনার মুভি পাওয়া গেছে:**\n{search_source}" if search_source else "🎬 **আপনার মুভি পাওয়া গেছে:**"
        await send_results(msg, results, f"{header_text}\n👇 নিচের লিংকে ক্লিক করুন:")
        return

    # ---------------------------------------------------------
    # কিছু না পেলে (Not Found + Smart Suggestion Logic)
    # ---------------------------------------------------------
    
    await loading_message.delete()
    
    final_query = tmdb_detected_title if tmdb_detected_title else cleaned_query
    encoded_final_query = urllib.parse.quote_plus(final_query)
    
    Google_Search_url = "https://www.google.com/search?q=" + urllib.parse.quote(final_query)
    
    req_btn = InlineKeyboardButton(
        f"✅ রিকোয়েস্ট করুন", 
        callback_data=f"request_movie_{user_id}_{encoded_final_query}"
    )
    google_btn = InlineKeyboardButton("🌐 গুগলে দেখুন", url=Google_Search_url)
    
    if tmdb_detected_title:
        # কেস ১: ইউজার ভুল লিখেছে, বোট সঠিক নাম পেয়েছে, কিন্তু সেই নামেও ডাটাবেসে ফাইল নেই
        alert_text = (
            f"❌ **'{query}'** পাওয়া যায়নি।\n\n"
            f"💡 **আপনি কি এটি খুঁজছিলেন?**\n"
            f"👉 **{tmdb_detected_title}**\n\n"
            f"দুঃখিত, এটিও আমাদের ডাটাবেসে নেই। নিচের বাটনে রিকোয়েস্ট করুন 👇"
        )
    else:
        # কেস ২: বোট কোনো সঠিক নামই খুঁজে পায়নি
        alert_text = (
            f"❌ দুঃখিত! **'{cleaned_query}'** আমাদের ডাটাবেসে নেই।\n\n"
            f"বানান সঠিক কিনা যাচাই করুন অথবা গুগলে চেক করুন।"
        )

    alert = await msg.reply_text(
        alert_text, 
        reply_markup=InlineKeyboardMarkup([[req_btn], [google_btn]]), 
        quote=True
    )
    asyncio.create_task(delete_message_later(alert.chat.id, alert.id))
    
    # Admin Alert
    admin_btns = get_admin_alert_buttons(user_id, encoded_final_query)
    
    for admin_id in ADMIN_IDS:
        try:
            status_text = f"🧹 Auto-Fix: `{final_query}`" if tmdb_detected_title else "⚠️ No Fix Found"
            await app.send_message(
                admin_id, 
                f"❗ *No Result Found!*\n"
                f"🔍 Search: `{query}`\n"
                f"{status_text}\n"
                f"👤 User: [{msg.from_user.first_name}](tg://user?id={user_id})", 
                reply_markup=admin_btns
            )
        except: pass

async def send_results(msg, results, header="🎬 আপনার কাঙ্ক্ষিত মুভি পাওয়া গেছে:"):
    buttons = []
    for movie in results:
        title = movie.get('title') or movie.get('original_title')
        buttons.append([
            InlineKeyboardButton(
                text=f"{title[:40]} ({movie.get('views_count', 0)} ভিউ)",
                url=f"https://t.me/{app.me.username}?start=watch_{movie['message_id']}"
            )
        ])
    m = await msg.reply(header, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    asyncio.create_task(delete_message_later(m.chat.id, m.id))

# ------------------- Callback Handlers -------------------

@app.on_callback_query(filters.regex(r"^noresult_(wrong|notyet|uploaded|coming|unreleased|processing)_(\d+)_([^ ]+)$") & filters.user(ADMIN_IDS))
async def handle_admin_reply(_, cq: CallbackQuery):
    parts = cq.data.split("_", 3)
    reason, user_id, original_query = parts[1], int(parts[2]), urllib.parse.unquote_plus(parts[3])

    messages = {
        "wrong": f"❌ **দুঃখিত! নামটিতে ভুল আছে।**\n\nভাইয়া, **'{original_query}'** নামে কোনো মুভি নেই বা বানান ভুল হয়েছে।",
        "unreleased": f"🚫 **অপ্রকাশিত মুভি!**\n\nভাইয়া, **'{original_query}'** মুভিটি এখনো অফিসিয়ালি রিলিজ হয়নি।",
        "uploaded": f"✅ **মুভিটি আমাদের কাছে আছে!**\n\nভাইয়া, **'{original_query}'** অলরেডি আছে। বানান ঠিক করে খুঁজুন।",
        "processing": f"♻️ **কাজ চলছে!**\n\nভাইয়া, **'{original_query}'** নিয়ে কাজ চলছে। শীঘ্রই পাবেন।",
        "coming": f"🚀 **শীঘ্রই আসবে!**\n\nভাইয়া, **'{original_query}'** খুব শীঘ্রই আসবে।",
        "notyet": f"⏳ **এখনো আসেনি!**\n\n**'{original_query}'** এখনো আসেনি, তবে নোট করা হয়েছে।"
    }
    try:
        sent = await app.send_message(user_id, messages[reason])
        asyncio.create_task(delete_message_later(sent.chat.id, sent.id))
        await cq.answer("Sent ✅", show_alert=True)
        await cq.message.edit_reply_markup(None)
    except Exception:
        await cq.answer("Failed to send ❌", show_alert=True)

def get_admin_alert_buttons(user_id, encoded_query):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ ভুল নাম", callback_data=f"noresult_wrong_{user_id}_{encoded_query}"),
         InlineKeyboardButton("🚫 রিলিজ হয়নি", callback_data=f"noresult_unreleased_{user_id}_{encoded_query}")],
        [InlineKeyboardButton("📤 আপলোড আছে", callback_data=f"noresult_uploaded_{user_id}_{encoded_query}"),
         InlineKeyboardButton("♻️ কাজ চলছে", callback_data=f"noresult_processing_{user_id}_{encoded_query}")],
        [InlineKeyboardButton("🚀 শীঘ্রই আসবে", callback_data=f"noresult_coming_{user_id}_{encoded_query}"),
         InlineKeyboardButton("⏳ এখনো আসেনি", callback_data=f"noresult_notyet_{user_id}_{encoded_query}")]
    ])

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data

    if data == "home_menu":
        greeting = get_greeting()
        user_mention = cq.from_user.mention
        bot_username = app.me.username
        start_caption = f"HEY {user_mention}, {greeting}\n\n🤖 **I AM {app.me.first_name},** ADVANCED BOT."
        btns = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔰 ADD ME TO YOUR GROUP 🔰", url=f"https://t.me/{bot_username}?startgroup=true")],
            [InlineKeyboardButton("HELP 📢", callback_data="help_menu"), InlineKeyboardButton("ABOUT 📘", callback_data="about_menu")],
            [InlineKeyboardButton("TOP SEARCHING ⭐", callback_data="top_searching"), InlineKeyboardButton("UPGRADE 🎟️", url=UPDATE_CHANNEL)]
        ])
        await cq.message.edit_caption(caption=start_caption, reply_markup=btns)

    elif data == "help_menu":
        help_text = "**⚙️ কমান্ড:**\n/start, /popular, /request, /feedback\n\n**Search:** মুভির নাম লিখুন।"
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="home_menu")]])
        await cq.message.edit_caption(caption=help_text, reply_markup=back_btn)

    elif data == "about_menu":
        about_text = f"**🤖 Bot:** {app.me.first_name}\n**🛠 Dev:** Ctgmovies23\n**🚀 Engine:** Motor Async + BS4"
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="home_menu")]])
        await cq.message.edit_caption(caption=about_text, reply_markup=back_btn)

    elif data == "top_searching":
        cursor = movies_col.find({"views_count": {"$exists": True}}).sort("views_count", -1).limit(RESULTS_COUNT)
        popular = await cursor.to_list(length=RESULTS_COUNT)
        if popular:
            text = "🔥 **Top Searching:**\n\n"
            for i, movie in enumerate(popular, 1):
                text += f"{i}. {movie['title']} ({movie.get('views_count', 0)})\n"
            back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="home_menu")]])
            await cq.message.edit_caption(caption=text, reply_markup=back_btn)
        else:
            await cq.answer("Empty!", show_alert=True)

    elif data.startswith("report_"):
        try:
            mid = int(data.split("_")[1])
            movie = await movies_col.find_one({"message_id": mid})
            title = movie.get("title", "Unknown") if movie else "Unknown"
            await cq.answer("রিপোর্ট পাঠানো হয়েছে ✅", show_alert=True)
            for aid in ADMIN_IDS:
                try: await app.send_message(aid, f"🚨 **Report!**\n🎬 {title}\n🆔 `{mid}`\n👤 {cq.from_user.mention}")
                except: pass
        except: await cq.answer("Error!", show_alert=True)
            
    elif data == "confirm_delete_all_movies":
        await movies_col.delete_many({})
        await cq.message.edit_text("✅ সব ডিলিট করা হয়েছে।")

    elif data == "cancel_delete_all_movies":
        await cq.message.edit_text("❌ বাতিল করা হয়েছে।")

    elif data.startswith("request_movie_"):
        _, uid, enc_name = data.split("_", 2)
        name = urllib.parse.unquote_plus(enc_name)
        await requests_col.insert_one({
            "user_id": int(uid),
            "username": cq.from_user.first_name,
            "movie_name": name,
            "request_time": datetime.now(timezone.utc),
            "status": "pending"
        })
        await cq.answer("অনুরোধ জমা হয়েছে ✅", show_alert=True)
        await cq.message.edit_text(f"✅ **'{name}'** এর জন্য অনুরোধ জমা নেওয়া হয়েছে।")
        
        btns = InlineKeyboardMarkup([[InlineKeyboardButton("Done", callback_data="noop")]])
        for aid in ADMIN_IDS:
            try: await app.send_message(aid, f"❗ *Inline Req*\n🎬 `{name}`\n👤 {cq.from_user.mention}", reply_markup=btns)
            except: pass

    elif "_" in data:
        await cq.answer()

user_last_start_time = {}

if __name__ == "__main__":
    print("🚀 Bot Started with FIXED Command & Search Logic...")
    app.loop.create_task(init_settings())
    app.loop.create_task(auto_group_messenger())
    app.run()
