#
# ----------------------------------------------------
# Developed by: Ctgmovies23
# Telegram Username: @ctgmovies23
# Channel Link: https://t.me/AllBotUpdatemy
# ----------------------------------------------------
#

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid
from pymongo import MongoClient, ASCENDING
from flask import Flask
from threading import Thread
import os
import re
import time
import math
from datetime import datetime, UTC, timedelta 
import asyncio
import urllib.parse
from fuzzywuzzy import process, fuzz 
from concurrent.futures import ThreadPoolExecutor

# ------------------- কনফিগারেশন -------------------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/TGLinkBase")
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

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- MongoDB সেটআপ -------------------
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
stats_col = db["stats"]
users_col = db["users"]
settings_col = db["settings"]
requests_col = db["requests"]
groups_col = db["groups"]

# ইনডেক্সিং
try:
    movies_col.drop_index("message_id_1")
except Exception:
    pass
try:
    movies_col.create_index("message_id", unique=True, background=True)
except Exception as e:
    print(f"Index Error: {e}")

movies_col.create_index("language", background=True)
movies_col.create_index([("title_clean", ASCENDING)], background=True)
movies_col.create_index([("views_count", ASCENDING)], background=True)

# ডিফল্ট সেটিংস
settings_col.update_one(
    {"key": "protect_forwarding"},
    {"$setOnInsert": {"value": True}},
    upsert=True
)

# ------------------- Flask অ্যাপ -------------------
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start() 

thread_pool_executor = ThreadPoolExecutor(max_workers=5)

# ------------------- হেল্পার ফাংশন -------------------
def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def extract_language(text):
    langs = ["Bengali", "Hindi", "English"]
    return next((lang for lang in langs if lang.lower() in text.lower()), None)

def extract_year(text):
    match = re.search(r'\b(19|20)\d{2}\b', text)
    return int(match.group(0)) if match else None

def get_readable_time(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

def get_greeting():
    utc_now = datetime.now(UTC)
    bd_hour = (utc_now.hour + 6) % 24
    if 5 <= bd_hour < 12:
        return "GOOD MORNING ☀️"
    elif 12 <= bd_hour < 17:
        return "GOOD AFTERNOON 🌤️"
    elif 17 <= bd_hour < 21:
        return "GOOD EVENING 🌇"
    else:
        return "GOOD NIGHT 🌙"

async def delete_message_later(chat_id, message_id, delay=300): 
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass

# [OPTIMIZED] ফাজি সার্চ লজিক
def find_corrected_matches(query_clean, all_movie_titles_data, score_cutoff=55, limit=5):
    if not all_movie_titles_data:
        return []
    
    choices = [item["title_clean"] for item in all_movie_titles_data]
    
    # WRatio ব্যবহার করা হচ্ছে যা টাইপো এবং আংশিক মিল ভালোভাবে ধরে
    matches_raw = process.extract(query_clean, choices, limit=limit, scorer=fuzz.WRatio)
    
    corrected_suggestions = []
    seen_titles = set()
    
    for matched_clean_title, score in matches_raw:
        if score >= score_cutoff:
            for movie_data in all_movie_titles_data:
                if movie_data["title_clean"] == matched_clean_title:
                    if movie_data["message_id"] not in seen_titles:
                        corrected_suggestions.append({
                            "title": movie_data["original_title"],
                            "message_id": movie_data["message_id"],
                            "language": movie_data["language"],
                            "views_count": movie_data.get("views_count", 0),
                            "score": score
                        })
                        seen_titles.add(movie_data["message_id"])
                    break
                    
    return sorted(corrected_suggestions, key=lambda x: x["score"], reverse=True)

# ------------------- অটো গ্রুপ মেসেঞ্জার -------------------
async def auto_group_messenger():
    print("✅ অটো গ্রুপ মেসেজ সিস্টেম চালু হয়েছে...")
    while True:
        all_groups = groups_col.find({})
        for group in all_groups:
            chat_id = group["_id"]
            try:
                sent = await app.send_message(chat_id, AUTO_MESSAGE_TEXT)
                if sent:
                    asyncio.create_task(delete_message_later(chat_id, sent.id, delay=AUTO_MSG_DELETE_TIME))
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except (PeerIdInvalid, UserIsBlocked):
                groups_col.delete_one({"_id": chat_id})
            except Exception:
                pass
            await asyncio.sleep(1.5) 
        await asyncio.sleep(AUTO_MSG_INTERVAL)

# ------------------- ব্রডকাস্ট ইঞ্জিন -------------------
async def broadcast_messages(user_ids, message_func, status_msg=None, total_users=0):
    success = 0
    failed = 0
    blocked = 0
    start_time = time.time()
    sem = asyncio.Semaphore(20)

    async def send_worker(user_id):
        nonlocal success, failed, blocked
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
                users_col.delete_one({"_id": user_id})
                blocked += 1
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
                speed = done / elapsed
                eta = (total_users - done) / speed if speed > 0 else 0
                percentage = (done / total_users) * 100
                progress_bar = f"[{'■' * int(percentage // 10)}{'□' * (10 - int(percentage // 10))}]"
                text = (
                    f"🚀 **ব্রডকাস্ট চলছে...**\n\n"
                    f"{progress_bar} **{percentage:.1f}%**\n\n"
                    f"✅ সফল: `{success}`\n"
                    f"❌ ব্যর্থ/ব্লক: `{failed}`\n"
                    f"👥 মোট: `{total_users}`\n"
                    f"⏱ সময়: `{get_readable_time(elapsed)}`\n"
                    f"⏳ বাকি সময়: `{get_readable_time(eta)}`"
                )
                try:
                    if status_msg.photo:
                        await status_msg.edit_caption(text)
                    else:
                        await status_msg.edit_text(text)
                except Exception:
                    pass

    updater_task = asyncio.create_task(update_status_loop())
    await asyncio.gather(*[send_worker(uid) for uid in user_ids])
    updater_task.cancel()

    elapsed = time.time() - start_time
    final_text = (
        f"✅ **ব্রডকাস্ট সম্পন্ন হয়েছে!**\n\n"
        f"✅ মোট পাঠানো হয়েছে: `{success}`\n"
        f"❌ ব্যর্থ হয়েছে: `{failed}` (ব্লক: {blocked})\n"
        f"⏱ মোট সময় লেগেছে: `{get_readable_time(elapsed)}`"
    )
    if status_msg:
        try:
            if status_msg.photo:
                await status_msg.edit_caption(final_text)
            else:
                await status_msg.edit_text(final_text)
        except Exception:
            pass
    return success, failed

# ------------------- অটো ব্রডকাস্ট -------------------
async def auto_broadcast_worker(movie_title, message_id, thumbnail_id=None):
    download_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("ডাউনলোড লিংক", url=f"https://t.me/{app.me.username}?start=watch_{message_id}")]
    ])
    notification_caption = f"🎬 **নতুন মুভি আপলোড হয়েছে!**\n\n**{movie_title}**\n\nএখনই ডাউনলোড করুন!"
    all_users_cursor = users_col.find({"notify": {"$ne": False}}, {"_id": 1})
    all_user_ids = [user["_id"] for user in all_users_cursor]
    total_users = len(all_user_ids)
    if total_users == 0: return

    status_msg = None
    for admin_id in ADMIN_IDS:
        try:
            pic_to_use = thumbnail_id if thumbnail_id else BROADCAST_PIC
            status_msg = await app.send_photo(
                admin_id, 
                photo=pic_to_use,
                caption=f"🚀 **অটো নোটিফিকেশন শুরু হচ্ছে...**\n👥 মোট ইউজার: `{total_users}`"
            )
            break
        except Exception:
            try:
                status_msg = await app.send_message(admin_id, f"🚀 **অটো নোটিফিকেশন শুরু হচ্ছে...**\n👥 মোট ইউজার: `{total_users}`")
                break
            except: pass

    async def send_func(user_id):
        sent_msg = None
        if thumbnail_id:
            sent_msg = await app.send_photo(user_id, photo=thumbnail_id, caption=notification_caption, reply_markup=download_button)
        else:
            sent_msg = await app.send_message(user_id, notification_caption, reply_markup=download_button)
        if sent_msg:
            asyncio.create_task(delete_message_later(sent_msg.chat.id, sent_msg.id, delay=86400))

    await broadcast_messages(all_user_ids, send_func, status_msg, total_users)

# ------------------- চ্যানেল পোস্ট হ্যান্ডলার -------------------
@app.on_message(filters.chat(CHANNEL_ID))
async def save_post(_, msg: Message):
    text = msg.text or msg.caption
    if not text:
        return
    thumbnail_file_id = None
    if msg.photo:
        thumbnail_file_id = msg.photo.file_id
    elif msg.video and msg.video.thumbs:
        thumbnail_file_id = msg.video.thumbs[0].file_id 

    movie_title = text.splitlines()[0]
    movie_to_save = {
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
    result = movies_col.update_one({"message_id": msg.id}, {"$set": movie_to_save}, upsert=True)
    if result.upserted_id is not None:
        setting = settings_col.find_one({"key": "global_notify"})
        if setting and setting.get("value"):
            asyncio.create_task(auto_broadcast_worker(movie_title, msg.id, thumbnail_file_id))

@app.on_message(filters.group, group=10)
async def log_group(_, msg: Message):
    groups_col.update_one(
        {"_id": msg.chat.id}, 
        {"$set": {"title": msg.chat.title, "active": True}}, 
        upsert=True
    )

# ------------------- স্টার্ট কমান্ড -------------------
user_last_start_time = {}

@app.on_message(filters.command("start"))
async def start(_, msg: Message):
    user_id = msg.from_user.id
    current_time = datetime.now(UTC)
    
    if user_id in user_last_start_time:
        time_since_last_start = current_time - user_last_start_time[user_id]
        if time_since_last_start < timedelta(seconds=2):
            return
    user_last_start_time[user_id] = current_time

    if len(msg.command) > 1 and msg.command[1].startswith("watch_"):
        message_id = int(msg.command[1].replace("watch_", ""))
        protect_setting = settings_col.find_one({"key": "protect_forwarding"})
        should_protect = protect_setting.get("value", True) if protect_setting else True
        try:
            copied_message = await app.copy_message(
                chat_id=msg.chat.id,        
                from_chat_id=CHANNEL_ID,    
                message_id=message_id,      
                protect_content=should_protect 
            )
            movie_data = movies_col.find_one({"message_id": message_id})
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
            movies_col.update_one(
                {"message_id": message_id},
                {"$inc": {"views_count": 1}}
            )
        except Exception:
            error_msg = await msg.reply_text("মুভিটি খুঁজে পাওয়া যায়নি বা লোড করা যায়নি।")
            asyncio.create_task(delete_message_later(error_msg.chat.id, error_msg.id))
        return 

    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"joined": datetime.now(UTC), "notify": True}},
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

    await msg.reply_photo(
        photo=START_PIC,
        caption=start_caption,
        reply_markup=btns
    )

# ------------------- অ্যাডমিন কমান্ড -------------------
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg: Message):
    if not msg.reply_to_message and len(msg.command) < 2:
        await msg.reply("ব্যবহার:\n১. কোনো মেসেজে রিপ্লাই দিয়ে `/broadcast` লিখুন।\n২. অথবা `/broadcast আপনার মেসেজ` লিখুন।")
        return
    all_users_cursor = users_col.find({}, {"_id": 1})
    all_user_ids = [user["_id"] for user in all_users_cursor]
    total_users = len(all_user_ids)
    if total_users == 0:
        await msg.reply("ডাটাবেসে কোনো ইউজার নেই।")
        return
    status_msg = None
    try:
        status_msg = await msg.reply_photo(
            photo=BROADCAST_PIC,
            caption=f"🚀 **ম্যানুয়াল ব্রডকাস্ট শুরু হচ্ছে...**\n👥 মোট টার্গেট: `{total_users}`"
        )
    except Exception:
        status_msg = await msg.reply(f"🚀 **ম্যানুয়াল ব্রডকাস্ট শুরু হচ্ছে...**\n👥 মোট টার্গেট: `{total_users}`")
    
    async def send_func(user_id):
        m = None
        if msg.reply_to_message:
            m = await msg.reply_to_message.copy(user_id)
        else:
            broadcast_text = msg.text.split(None, 1)[1]
            m = await app.send_message(user_id, broadcast_text, disable_web_page_preview=True)

    await broadcast_messages(all_user_ids, send_func, status_msg, total_users)

@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg: Message):
    if len(msg.command) < 2:
        error_msg = await msg.reply("অনুগ্রহ করে /feedback এর পর আপনার মতামত লিখুন।")
        asyncio.create_task(delete_message_later(error_msg.chat.id, error_msg.id))
        return
    feedback_col.insert_one({
        "user": msg.from_user.id,
        "text": msg.text.split(None, 1)[1],
        "time": datetime.now(UTC)
    })
    m = await msg.reply("আপনার মতামতের জন্য ধন্যবাদ!")
    asyncio.create_task(delete_message_later(m.chat.id, m.id))

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg: Message):
    total_groups = groups_col.count_documents({})
    stats_msg = await msg.reply(
        f"""মোট ব্যবহারকারী: {users_col.count_documents({})}
মোট গ্রুপ: {total_groups}
মোট মুভি: {movies_col.count_documents({})}
মোট ফিডব্যাক: {feedback_col.count_documents({})}
মোট অনুরোধ: {requests_col.count_documents({})}"""
    )
    asyncio.create_task(delete_message_later(stats_msg.chat.id, stats_msg.id))

@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify_command(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        error_msg = await msg.reply("ব্যবহার: /notify on অথবা /notify off")
        asyncio.create_task(delete_message_later(error_msg.chat.id, error_msg.id))
        return
    new_value = True if msg.command[1] == "on" else False
    settings_col.update_one(
        {"key": "global_notify"},
        {"$set": {"value": new_value}},
        upsert=True
    )
    status = "চালু" if new_value else "বন্ধ"
    reply_msg = await msg.reply(f"✅ গ্লোবাল নোটিফিকেশন {status} করা হয়েছে!")
    asyncio.create_task(delete_message_later(reply_msg.chat.id, reply_msg.id))

@app.on_message(filters.command("forward_toggle") & filters.user(ADMIN_IDS))
async def toggle_forward_protection(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        error_msg = await msg.reply("ব্যবহার: /forward_toggle on (ফরওয়ার্ডিং বন্ধ) অথবা /forward_toggle off (ফরওয়ার্ডিং চালু)")
        asyncio.create_task(delete_message_later(error_msg.chat.id, error_msg.id))
        return
    new_value_for_protect_content = True if msg.command[1] == "on" else False
    settings_col.update_one(
        {"key": "protect_forwarding"},
        {"$set": {"value": new_value_for_protect_content}},
        upsert=True
    )
    status = "বন্ধ" if new_value_for_protect_content else "চালু"
    reply_msg = await msg.reply(f"✅ ইউজারদের জন্য মুভি ফরওয়ার্ডিং {status} করা হয়েছে!")
    asyncio.create_task(delete_message_later(reply_msg.chat.id, reply_msg.id))

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_specific_movie(_, msg: Message):
    if len(msg.command) < 2:
        error_msg = await msg.reply("অনুগ্রহ করে মুভির টাইটেল দিন। ব্যবহার: `/delete_movie <মুভির টাইটেল>`")
        asyncio.create_task(delete_message_later(error_msg.chat.id, error_msg.id))
        return
    movie_title_to_delete = msg.text.split(None, 1)[1].strip()
    movie_to_delete = movies_col.find_one({"title": {"$regex": re.escape(movie_title_to_delete), "$options": "i"}})
    if not movie_to_delete:
        cleaned_title_to_delete = clean_text(movie_title_to_delete)
        movie_to_delete = movies_col.find_one({"title_clean": {"$regex": f"^{re.escape(cleaned_title_to_delete)}$", "$options": "i"}})
    if movie_to_delete:
        movies_col.delete_one({"_id": movie_to_delete["_id"]})
        reply_msg = await msg.reply(f"মুভি **{movie_to_delete['title']}** সফলভাবে ডিলিট করা হয়েছে।")
        asyncio.create_task(delete_message_later(reply_msg.chat.id, reply_msg.id))
    else:
        error_msg = await msg.reply(f"**{movie_title_to_delete}** নামের কোনো মুভি খুঁজে পাওয়া যায়নি।")
        asyncio.create_task(delete_message_later(error_msg.chat.id, error_msg.id))

@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies_command(_, msg: Message):
    confirmation_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("হ্যাঁ, সব ডিলিট করুন", callback_data="confirm_delete_all_movies")],
        [InlineKeyboardButton("না, বাতিল করুন", callback_data="cancel_delete_all_movies")]
    ])
    reply_msg = await msg.reply("আপনি কি নিশ্চিত যে আপনি ডাটাবেস থেকে **সব মুভি** ডিলিট করতে চান? এই প্রক্রিয়াটি অপরিবর্তনীয়!", reply_markup=confirmation_button)
    asyncio.create_task(delete_message_later(reply_msg.chat.id, reply_msg.id))

# ------------------- অ্যাডমিন রিপ্লাই হ্যান্ডলার -------------------
@app.on_callback_query(filters.regex(r"^noresult_(wrong|notyet|uploaded|coming|unreleased|processing)_(\d+)_([^ ]+)$") & filters.user(ADMIN_IDS))
async def handle_admin_reply(_, cq: CallbackQuery):
    parts = cq.data.split("_", 3)
    reason = parts[1]
    user_id = int(parts[2])
    encoded_query = parts[3]
    original_query = urllib.parse.unquote_plus(encoded_query)

    messages = {
        "wrong": f"❌ **দুঃখিত! নামটিতে ভুল আছে।**\n\nভাইয়া, **'{original_query}'** নামে কোনো মুভি নেই বা বানান ভুল হয়েছে। দয়া করে Google থেকে সঠিক বানানটি দেখে আবার সার্চ করুন।",
        "unreleased": f"🚫 **অপ্রকাশিত মুভি!**\n\nভাইয়া, **'{original_query}'** মুভিটি এখনো অফিসিয়ালি ডিজিটাল/ওটিটি-তে রিলিজ হয়নি। রিলিজ হওয়ার সাথে সাথেই আমাদের চ্যানেলে পেয়ে যাবেন।",
        "uploaded": f"✅ **মুভিটি আমাদের কাছে আছে!**\n\nভাইয়া, **'{original_query}'** মুভিটি অলরেডি আপলোড করা আছে। আপনি সম্ভবত ভুল বানানে সার্চ করেছেন। দয়া করে সঠিক বানানে আবার চেষ্টা করুন।",
        "processing": f"♻️ **কাজ চলছে!**\n\nভাইয়া, **'{original_query}'** মুভিটি নিয়ে আমরা কাজ করছি। কিছুক্ষণের মধ্যেই আপলোড করা হবে। সাথে থাকার জন্য ধন্যবাদ!",
        "coming": f"🚀 **শীঘ্রই আসবে!**\n\nভাইয়া, **'{original_query}'** মুভিটি খুব শীঘ্রই আমাদের চ্যানেলে আসবে। আমরা এটি সংগ্রহের চেষ্টা করছি। অনুগ্রহ করে অপেক্ষা করুন।",
        "notyet": f"⏳ **এখনো আসেনি!**\n\n**'{original_query}'** মুভিটি এখনো আমাদের ডাটাবেসে নেই। তবে আমরা এটি নোট করে রেখেছি, শীঘ্রই যুক্ত করা হবে।"
    }
    try:
        m_sent = await app.send_message(user_id, messages[reason])
        asyncio.create_task(delete_message_later(m_sent.chat.id, m_sent.id))
        await cq.answer("ব্যবহারকারীকে জানানো হয়েছে ✅", show_alert=True)
        btn_text = {
            "wrong": "ভুল নাম ❌", "unreleased": "রিলিজ হয়নি 🚫", 
            "uploaded": "আপলোড আছে ✅", "processing": "কাজ চলছে ♻️",
            "coming": "শীঘ্রই আসবে 🚀", "notyet": "এখনো আসেনি ⏳"
        }
        await cq.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ রিপ্লাই দেওয়া হয়েছে: {btn_text.get(reason, 'সম্পন্ন')}", callback_data="noop")
        ]]))
    except Exception:
        await cq.answer("ব্যবহারকারীকে মেসেজ পাঠানো যায়নি (হয়তো ব্লক করেছে) ❌", show_alert=True)

@app.on_message(filters.command("popular") & (filters.private | filters.group))
async def popular_movies(_, msg: Message):
    popular_movies_list = list(movies_col.find(
        {"views_count": {"$exists": True}}
    ).sort("views_count", -1).limit(RESULTS_COUNT))

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
        reply_markup = InlineKeyboardMarkup(buttons)
        m = await msg.reply_text("🔥 বর্তমানে সবচেয়ে জনপ্রিয় মুভিগুলো:\n\n", reply_markup=reply_markup, quote=True)
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
    else:
        m = await msg.reply_text("দুঃখিত, বর্তমানে কোনো জনপ্রিয় মুভি পাওয়া যায়নি।", quote=True)
        asyncio.create_task(delete_message_later(m.chat.id, m.id))

@app.on_message(filters.command("request") & filters.private)
async def request_movie(_, msg: Message):
    if len(msg.command) < 2:
        error_msg = await msg.reply("অনুগ্রহ করে /request এর পর মুভির নাম লিখুন। উদাহরণ: `/request The Creator`", quote=True)
        asyncio.create_task(delete_message_later(error_msg.chat.id, error_msg.id))
        return
    movie_name = msg.text.split(None, 1)[1].strip()
    user_id = msg.from_user.id
    username = msg.from_user.username or msg.from_user.first_name
    requests_col.insert_one({
        "user_id": user_id,
        "username": username,
        "movie_name": movie_name,
        "request_time": datetime.now(UTC),
        "status": "pending"
    })
    m = await msg.reply(f"আপনার অনুরোধ **'{movie_name}'** সফলভাবে জমা দেওয়া হয়েছে। এডমিনরা এটি পর্যালোচনা করবেন।", quote=True)
    asyncio.create_task(delete_message_later(m.chat.id, m.id))
    encoded_movie_name = urllib.parse.quote_plus(movie_name)
    admin_request_btns = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ সম্পন্ন হয়েছে", callback_data=f"req_fulfilled_{user_id}_{encoded_movie_name}"),
        InlineKeyboardButton("❌ বাতিল করা হয়েছে", callback_data=f"req_rejected_{user_id}_{encoded_movie_name}")
    ]])
    for admin_id in ADMIN_IDS:
        try:
            await app.send_message(
                admin_id,
                f"❗ *নতুন মুভির অনুরোধ!*\n\n"
                f"🎬 মুভির নাম: `{movie_name}`\n"
                f"👤 ইউজার: [{username}](tg://user?id={user_id}) (`{user_id}`)",
                reply_markup=admin_request_btns,
                disable_web_page_preview=True
            )
        except Exception:
            pass

# ------------------- স্মার্ট সার্চ হ্যান্ডলার (UPDATED) -------------------
@app.on_message(filters.text & (filters.group | filters.private))
async def search(_, msg: Message):
    query = msg.text.strip()
    if not query:
        return
    
    if msg.chat.type in ["group", "supergroup"]:
        groups_col.update_one({"_id": msg.chat.id}, {"$set": {"title": msg.chat.title, "active": True}}, upsert=True)
        if len(query) < 3: return
        if msg.reply_to_message or msg.from_user.is_bot: return
        if not re.search(r'[a-zA-Z0-9]', query): return

    user_id = msg.from_user.id
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"last_query": query}, "$setOnInsert": {"joined": datetime.now(UTC)}},
        upsert=True
    )

    loading_message = await msg.reply("🔎 লোড হচ্ছে...", quote=True)
    
    query_title_only = re.sub(r'\b(19|20)\d{2}\b', '', query).strip()
    if not query_title_only:
        query_title_only = query 

    query_clean = clean_text(query_title_only)

    # ১. প্রথমে Exact এবং Starts With চেক করবে
    exact_match = list(movies_col.find({"title_clean": query_clean}).limit(RESULTS_COUNT))
    
    starts_with_match = list(movies_col.find({
        "title_clean": {"$regex": f"^{re.escape(query_clean)}", "$options": "i"}
    }).limit(RESULTS_COUNT))
    
    final_results = exact_match + [m for m in starts_with_match if m["message_id"] not in [e["message_id"] for e in exact_match]]
    final_results = final_results[:RESULTS_COUNT]

    if final_results:
        await loading_message.delete()
        buttons = []
        for movie in final_results:
            buttons.append([
                InlineKeyboardButton(
                    text=f"{movie['title'][:40]} ({movie.get('views_count', 0)} ভিউ)",
                    url=f"https://t.me/{app.me.username}?start=watch_{movie['message_id']}"
                )
            ])
        m = await msg.reply("🎬 আপনার কাঙ্ক্ষিত মুভিটি পাওয়া গেছে:", reply_markup=InlineKeyboardMarkup(buttons), quote=True)
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
        return

    # ২. যদি কোনো রেজাল্ট না পাওয়া যায়, তখন Fuzzy Logic / Did You Mean চেক করবে
    all_movie_data_cursor = movies_col.find(
        {}, 
        {"title_clean": 1, "original_title": "$title", "message_id": 1, "language": 1, "views_count": 1}
    )
    all_movie_data = list(all_movie_data_cursor)
    
    corrected_suggestions = await asyncio.get_event_loop().run_in_executor(
        thread_pool_executor,
        find_corrected_matches,
        query_clean,
        all_movie_data,
        50, # স্কোর কাটঅফ ৫০
        RESULTS_COUNT
    )
    await loading_message.delete()

    if corrected_suggestions:
        best_match_name = corrected_suggestions[0]['title']
        
        buttons = []
        for movie in corrected_suggestions:
            buttons.append([
                InlineKeyboardButton(
                    text=f"{movie['title'][:40]} ({movie.get('views_count', 0)} ভিউ)",
                    url=f"https://t.me/{app.me.username}?start=watch_{movie['message_id']}"
                )
            ])
        
        did_you_mean_text = f"""
❌ **আপনার বানানে হয়তো ভুল আছে!**

🤔 আপনি কি **{best_match_name}** খুঁজছেন?
নিচে আপনার সার্চের সাথে সবচেয়ে মিল থাকা রেজাল্টগুলো দেওয়া হলো:
"""
        m = await msg.reply(did_you_mean_text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
        asyncio.create_task(delete_message_later(m.chat.id, m.id))

        # [NEW UPDATE] এডমিনকে নোটিফিকেশন পাঠানো যখন সাজেশন দেওয়া হয়
        encoded_query = urllib.parse.quote_plus(query)
        admin_fuzzy_btns = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("❌ ভুল নাম রিপ্লাই", callback_data=f"noresult_wrong_{user_id}_{encoded_query}"),
                InlineKeyboardButton("📤 আপলোড আছে রিপ্লাই", callback_data=f"noresult_uploaded_{user_id}_{encoded_query}")
            ]
        ])

        for admin_id in ADMIN_IDS:
            try:
                await app.send_message(
                    admin_id,
                    f"⚠️ **বানান ভুল / সাজেশন অ্যালার্ট!**\n\n"
                    f"🔍 ইউজার সার্চ করেছে: `{query}`\n"
                    f"🤖 বট সাজেশন দিয়েছে: `{best_match_name}`\n"
                    f"👤 ইউজার: [{msg.from_user.first_name}](tg://user?id={user_id}) (`{user_id}`)\n\n"
                    f"ℹ️ *ইউজার মুভিটি সরাসরি পায়নি, বট তাকে সাজেশন দিয়েছে।*",
                    reply_markup=admin_fuzzy_btns,
                    disable_web_page_preview=True
                )
            except Exception:
                pass
        
    else:
        # ৩. কিছুই না পাওয়া গেলে
        Google_Search_url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        request_button = InlineKeyboardButton("এই মুভির জন্য অনুরোধ করুন", callback_data=f"request_movie_{user_id}_{urllib.parse.quote_plus(query)}")
        google_button_row = [InlineKeyboardButton("গুগলে সার্চ করুন", url=Google_Search_url)]
        reply_markup_for_no_result = InlineKeyboardMarkup([google_button_row, [request_button]])
        alert = await msg.reply_text( 
            """
❌ দুঃখিত! আপনার খোঁজা মুভিটি খুঁজে পাওয়া যায়নি।

যদি মুভির নামটি ভুল হয়ে থাকে, তাহলে আপনি নিচের বাটনে ক্লিক করে Google থেকে সঠিক নাম দেখে নিতে পারেন।
অথবা, আপনার পছন্দের মুভিটি আমাদের কাছে অনুরোধ করতে পারেন।
""",
            reply_markup=reply_markup_for_no_result,
            quote=True
        )
        asyncio.create_task(delete_message_later(alert.chat.id, alert.id))
        
        encoded_query = urllib.parse.quote_plus(query)
        admin_btns = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("❌ ভুল নাম", callback_data=f"noresult_wrong_{user_id}_{encoded_query}"),
                InlineKeyboardButton("🚫 রিলিজ হয়নি", callback_data=f"noresult_unreleased_{user_id}_{encoded_query}")
            ],
            [
                InlineKeyboardButton("📤 আপলোড আছে", callback_data=f"noresult_uploaded_{user_id}_{encoded_query}"),
                InlineKeyboardButton("♻️ কাজ চলছে", callback_data=f"noresult_processing_{user_id}_{encoded_query}")
            ],
            [
                InlineKeyboardButton("🚀 শীঘ্রই আসবে", callback_data=f"noresult_coming_{user_id}_{encoded_query}"),
                InlineKeyboardButton("⏳ এখনো আসেনি", callback_data=f"noresult_notyet_{user_id}_{encoded_query}")
            ]
        ])
        
        for admin_id in ADMIN_IDS:
            try:
                await app.send_message(
                    admin_id,
                    f"❗ *নতুন মুভি খোঁজা হয়েছে কিন্তু পাওয়া যায়নি!*\n\n"
                    f"🔍 অনুসন্ধান: `{query}`\n"
                    f"👤 ইউজার: [{msg.from_user.first_name}](tg://user?id={user_id}) (`{user_id}`)",
                    reply_markup=admin_btns,
                    disable_web_page_preview=True
                )
            except Exception:
                pass

# ------------------- কলব্যাক হ্যান্ডলার -------------------
@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data

    if data == "home_menu":
        greeting = get_greeting()
        user_mention = cq.from_user.mention
        bot_username = app.me.username
        start_caption = f"""
HEY {user_mention}, {greeting}

🤖 **I AM {app.me.first_name},** THE MOST
POWERFUL AUTO FILTER BOT WITH 
PREMIUM FEATURES.
"""
        btns = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔰 ADD ME TO YOUR GROUP 🔰", url=f"https://t.me/{bot_username}?startgroup=true")],
            [InlineKeyboardButton("HELP 📢", callback_data="help_menu"), InlineKeyboardButton("ABOUT 📘", callback_data="about_menu")],
            [InlineKeyboardButton("TOP SEARCHING ⭐", callback_data="top_searching"), InlineKeyboardButton("UPGRADE 🎟️", url=UPDATE_CHANNEL)]
        ])
        await cq.message.edit_caption(caption=start_caption, reply_markup=btns)

    elif data == "help_menu":
        help_text = """
**⚙️ বটের সকল কমান্ড (Commands):**

/start - বট চালু করুন
/popular - জনপ্রিয় মুভি দেখুন
/request <নাম> - মুভি রিকোয়েস্ট করুন
/feedback <বার্তা> - অ্যাডমিনকে মতামত জানান

**🔎 সার্চ:** যেকোনো মুভির নাম লিখে পাঠালেই হবে।
**🛑 রিপোর্ট:** ডাউনলোড লিংক কাজ না করলে 'Report' বাটনে ক্লিক করবেন।
"""
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="home_menu")]])
        await cq.message.edit_caption(caption=help_text, reply_markup=back_btn)

    elif data == "about_menu":
        about_text = f"""
**🤖 Bot Name:** {app.me.first_name}
**🛠 Developed By:** Ctgmovies23
**📣 Channel:** [Click Here]({UPDATE_CHANNEL})
**🧠 Language:** Python 3 (Pyrogram)
**🗄 Database:** MongoDB

এই বটটি সম্পূর্ণ অটোমেটিক। মুভির নাম লিখলে এটি ডাটাবেস থেকে খুঁজে বের করে দেয়।
"""
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="home_menu")]])
        await cq.message.edit_caption(caption=about_text, reply_markup=back_btn)

    elif data == "top_searching":
        popular_movies_list = list(movies_col.find({"views_count": {"$exists": True}}).sort("views_count", -1).limit(RESULTS_COUNT))
        if popular_movies_list:
            text = "🔥 **জনপ্রিয় সার্চসমূহ:**\n\n"
            for i, movie in enumerate(popular_movies_list, 1):
                text += f"{i}. {movie['title']} ({movie.get('views_count', 0)} views)\n"
            back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="home_menu")]])
            await cq.message.edit_caption(caption=text, reply_markup=back_btn)
        else:
            await cq.answer("এখনো কোনো তথ্য নেই!", show_alert=True)

    elif data.startswith("report_"):
        try:
            message_id = int(data.split("_")[1])
            user_id = cq.from_user.id
            username = cq.from_user.username or cq.from_user.first_name
            movie = movies_col.find_one({"message_id": message_id})
            movie_title = movie.get("title", "অজানা মুভি") if movie else "অজানা মুভি"
            await cq.answer("✅ আপনার রিপোর্ট অ্যাডমিনের কাছে পাঠানো হয়েছে।", show_alert=True)
            report_msg = (
                f"🚨 **মুভি রিপোর্ট / লিংক সমস্যা!**\n\n"
                f"🎬 **মুভি:** {movie_title}\n"
                f"🆔 **মেসেজ আইডি:** `{message_id}`\n"
                f"👤 **রিপোর্টার:** [{username}](tg://user?id={user_id}) (`{user_id}`)\n\n"
                f"⚠️ **সমস্যা:** ইউজার জানিয়েছেন লিংকটি কাজ করছে না।"
            )
            for admin_id in ADMIN_IDS:
                try:
                    await app.send_message(admin_id, report_msg)
                except Exception:
                    pass
        except Exception:
            await cq.answer("রিপোর্ট পাঠাতে সমস্যা হয়েছে।", show_alert=True)
            
    elif data == "confirm_delete_all_movies":
        movies_col.delete_many({})
        reply_msg = await cq.message.edit_text("✅ ডাটাবেস থেকে সব মুভি সফলভাবে ডিলিট করা হয়েছে।")
        asyncio.create_task(delete_message_later(reply_msg.chat.id, reply_msg.id))
        await cq.answer("সব মুভি ডিলিট করা হয়েছে।")

    elif data == "cancel_delete_all_movies":
        reply_msg = await cq.message.edit_text("❌ সব মুভি ডিলিট করার প্রক্রিয়া বাতিল করা হয়েছে।")
        asyncio.create_task(delete_message_later(reply_msg.chat.id, reply_msg.id))
        await cq.answer("বাতিল করা হয়েছে।")

    elif data.startswith("request_movie_"):
        _, user_id_str, encoded_movie_name = data.split("_", 2)
        user_id = int(user_id_str)
        movie_name = urllib.parse.unquote_plus(encoded_movie_name)
        username = cq.from_user.username or cq.from_user.first_name
        requests_col.insert_one({
            "user_id": user_id,
            "username": username,
            "movie_name": movie_name,
            "request_time": datetime.now(UTC),
            "status": "pending"
        })
        await cq.answer(f"আপনার অনুরোধ '{movie_name}' সফলভাবে জমা দেওয়া হয়েছে।", show_alert=True)
        admin_request_btns = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ সম্পন্ন হয়েছে", callback_data=f"req_fulfilled_{user_id}_{encoded_movie_name}"),
            InlineKeyboardButton("❌ বাতিল করা হয়েছে", callback_data=f"req_rejected_{user_id}_{encoded_movie_name}")
        ]])
        for admin_id in ADMIN_IDS:
            try:
                await app.send_message(
                    admin_id,
                    f"❗ *নতুন মুভির অনুরোধ (ইনলাইন বাটন থেকে)!*\n\n"
                    f"🎬 মুভির নাম: `{movie_name}`\n"
                    f"👤 ইউজার: [{username}](tg://user?id={user_id}) (`{user_id}`)",
                    reply_markup=admin_request_btns,
                    disable_web_page_preview=True
                )
            except Exception:
                pass
        try:
            edited_msg = await cq.message.edit_text(
                f"❌ দুঃখিত! আপনার খোঁজা মুভিটি খুঁজে পাওয়া যায়নি।\n\n"
                f"আপনার অনুরোধ **'{movie_name}'** জমা দেওয়া হয়েছে। এডমিনরা এটি পর্যালোচনা করবেন।",
                reply_markup=None
            )
            asyncio.create_task(delete_message_later(edited_msg.chat.id, edited_msg.id))
        except Exception:
            pass

    elif "_" in data:
        await cq.answer()

if __name__ == "__main__":
    print("বট শুরু হচ্ছে...")
    app.loop.create_task(auto_group_messenger())
    app.run()
