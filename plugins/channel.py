# --| Optimized for @MzBotz | Original Format + Live Merging + File Thumbnail |--#
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from info import CHANNELS, MOVIE_UPDATE_CHANNEL
from database.ia_filterdb import save_file, unpack_new_file_id
from utils import temp
from difflib import SequenceMatcher
from collections import defaultdict
import logging
import os
import re
import html
import asyncio

media_filter = filters.document | filters.video | filters.audio

ACTIVE_POSTS = {}
MERGE_LOCK = asyncio.Lock()
DEFAULT_POSTER_URL = "https://files.catbox.moe/oeecjg.jpg"

UPDATE_CAPTION = """<blockquote>⚡️ <b>NEW {} ADDED</b></blockquote>

🎬 <b>Title:</b> <code>{}</code>
🎧 <b>Audio:</b> {}
📊 <b>Quality:</b> {}

<blockquote>📁 <b>Available Files & Links:</b>
{}</blockquote>
<blockquote>🔥 <b>Powered By</b> ➔ <a href='https://t.me/MzBotz'><b>𝐌𝐳𝐁𝐨𝐭𝐳™</b></a> ⚡️</blockquote>"""

CAPTION_LANGUAGES = [
    # Indian & Regional
    "Hindi", "English", "Tamil", "Telugu", "Malayalam", "Kannada", "Bengali", 
    "Marathi", "Punjabi", "Gujarati", "Bhojpuri", "Urdu", "Odia", "Assamese", 
    "Haryanvi", "Rajasthani", "Nepali", "Sinhala", "Santhali", "Kashmiri", "Konkani",
    # Asian
    "Korean", "Japanese", "Chinese", "Mandarin", "Cantonese", "Thai", 
    "Vietnamese", "Indonesian", "Tagalog", "Filipino", "Malay", "Persian", 
    "Arabic", "Turkish", "Hebrew",
    # World
    "Spanish", "French", "German", "Russian", "Italian", "Portuguese", 
    "Dutch", "Polish", "Swedish", "Norwegian", "Danish", "Finnish", 
    "Greek", "Ukrainian", "Romanian", "Hungarian", "Czech"
]


def format_file_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def get_qualities(text):
    qualities = [
        "480p", "720p", "720p HEVC", "1080p", "1080p HEVC", "2160p", "4k", "ORG", "HDRip", "WEB-DL"
    ]
    found = [q for q in qualities if q.lower() in text.lower()]
    return ", ".join(found) or "HDRip"


def Jisshu_qualities(text, file_name):
    qualities = ["480p", "720p", "720p HEVC", "1080p", "1080p HEVC", "2160p"]
    combined_text = (text.lower() + " " + file_name.lower()).strip()
    if "hevc" in combined_text:
        for quality in qualities:
            if "HEVC" in quality and quality.split()[0].lower() in combined_text:
                return quality
    for quality in qualities:
        if "HEVC" not in quality and quality.lower() in combined_text:
            return quality
    return "720p"


def clean_movie_title(file_name):
    clean = re.sub(
        r"http\S+|@\w+|#\w+", "", file_name
    ).replace("_", " ").replace(".", " ").strip()
    
    series_split = re.search(
        r"(?i)(?:\bnone\b|\bs\d{1,2}\s*e\d{1,4}|\bs\d{1,2}|\bseason\s*\d{1,2}|\be(?:p)?\d{1,4}\b)",
        clean
    )
    if series_split and series_split.start() > 2:
        clean = clean[: series_split.start()].strip()
        
    year_match = re.search(r"\b(19|20)\d{2}\b", clean)
    if year_match and clean.find(year_match.group(0)) > 2:
        clean = clean[: clean.find(year_match.group(0))].strip()
        
    return re.sub(r"\s+", " ", clean).strip() or file_name


def find_similar_key(new_key):
    norm_new = re.sub(r"[^a-zA-Z0-9]", "", new_key).lower()
    for existing_key in ACTIVE_POSTS.keys():
        norm_exist = re.sub(r"[^a-zA-Z0-9]", "", existing_key).lower()
        if norm_new == norm_exist:
            return existing_key
        ratio = SequenceMatcher(None, norm_new, norm_exist).ratio()
        if ratio >= 0.85:
            return existing_key
    return None


def generate_caption_body(post_data):
    """Aapke original bot ka clean episode / quality links format"""
    episode_map = post_data["episode_map"]
    combined_links = post_data["combined_links"]
    other_files = post_data["other_files"]
    bot_uname = temp.U_NAME

    quality_text = ""

    def ep_sort_key(ep_str):
        nums = re.findall(r"\d+", ep_str)
        return (int(nums[0]) if len(nums) > 0 else 0, int(nums[1]) if len(nums) > 1 else 0)

    # 1. Single Episodes (Sorted)
    for ep in sorted(episode_map.keys(), key=ep_sort_key):
        qualities = episode_map[ep]
        parts = []
        for q in sorted(qualities.keys()):
            f = qualities[q]
            size_str = f" [<code>{f['file_size']}</code>]" if f.get('file_size') else ""
            parts.append(f"<a href='https://t.me/{bot_uname}?start=file_0_{f['file_id']}'>📥 Download ({q})</a>{size_str}")
        quality_text += f"📦 {ep} : " + " - ".join(parts) + "\n"

    # 2. Combined Packs
    if combined_links:
        quality_text += "\n<b>COMBiNED</b> ✅\n\n"
        for c in combined_links:
            size_str = f" [<code>{c['file_size']}</code>]" if c.get('file_size') else ""
            quality_text += f"📦 {c['ep']} ({c['quality']}){size_str} : <a href='https://t.me/{bot_uname}?start=file_0_{c['file_id']}'>📥 Download</a>\n"

    # 3. Movies / Non-Episode Files
    if not quality_text and other_files:
        quality_groups = defaultdict(list)
        for f in other_files:
            quality_groups[f["quality"]].append(f)
        for q, q_files in sorted(quality_groups.items()):
            links = [
                f"<a href='https://t.me/{bot_uname}?start=file_0_{f['file_id']}'>📥 Download</a> [<code>{f['file_size']}</code>]"
                for f in q_files
            ]
            quality_text += f"📦 <b>{q}</b> : " + " | ".join(links) + "\n"

    return UPDATE_CAPTION.format(
        post_data["kind"],
        post_data["title"],
        ", ".join(sorted(post_data["languages"])) if post_data["languages"] else "Not Idea",
        post_data["main_quality"],
        quality_text.strip()
    )


@Client.on_message(filters.chat(CHANNELS) & media_filter)
async def media(bot, message):
    for file_type in ("document", "video", "audio"):
        media_obj = getattr(message, file_type, None)
        if media_obj is not None:
            break
    else:
        return

    media_obj.file_type = file_type
    media_obj.caption = message.caption

    # Database me save karein
    try:
        res = save_file(media_obj)
        if asyncio.iscoroutine(res):
            await res
    except Exception as e:
        logging.error(f"Error saving to DB: {e}")
        return

    # Non-blocking background worker (Taaki Telegram se 100 files drop na hon)
    asyncio.create_task(process_media_post(bot, media_obj))


async def process_media_post(bot, media_obj):
    downloaded_thumb_path = None
    try:
        target_channel = MOVIE_UPDATE_CHANNEL
        if not target_channel:
            return

        raw_name = getattr(media_obj, "file_name", None) or ""
        caption_text = media_obj.caption or ""
        check_text = f"{raw_name} {caption_text}".strip()

        file_id, _ = unpack_new_file_id(media_obj.file_id)
        file_size_str = format_file_size(media_obj.file_size)
        quality = Jisshu_qualities(caption_text, raw_name)
        main_quality = await get_qualities(check_text) if asyncio.iscoroutinefunction(get_qualities) else get_qualities(check_text)

        clean_title = clean_movie_title(raw_name)
        year_match = re.search(r"\b(19|20)\d{2}\b", check_text)
        year = year_match.group(0) if year_match else ""

        # Language Detection
        detected_langs = set()
        full_text_lower = check_text.lower()
        if "multi" in full_text_lower:
            detected_langs.add("Multi Audio")
        elif "dual" in full_text_lower:
            detected_langs.add("Dual Audio")

        for lang in CAPTION_LANGUAGES:
            if re.search(r"\b" + re.escape(lang.lower()) + r"\b", full_text_lower):
                detected_langs.add(lang)

        # Episode Check (1 - 9999 support)
        combined_pattern = re.compile(
            r"(?:S(\d{1,2}))?[\s_\[\-(]*E(?:P)?(\d{1,4})\s*[-~to]+\s*E?(?:P)?(\d{1,4})[\]\)\s_]*",
            re.IGNORECASE
        )
        episode_pattern = re.compile(
            r"(?:S(\d{1,2}))?[\s_\[\-(]*E(?:P)?(\d{1,4})\b",
            re.IGNORECASE
        )

        comb_match = combined_pattern.search(check_text)
        ep_match = episode_pattern.search(check_text)
        kind = "SERIES" if (comb_match or ep_match or "s0" in check_text.lower()) else "MOVIE"

        # Unique Key for Live Grouping
        current_merge_key = f"{clean_title.lower()}_{year}".strip()

        file_info = {
            "file_id": file_id,
            "quality": quality,
            "file_size": file_size_str
        }

        async with MERGE_LOCK:
            matched_key = find_similar_key(current_merge_key)

            # CASE 1: Pehle Se Post Hai -> Live Caption Update
            if matched_key:
                p_data = ACTIVE_POSTS[matched_key]
                p_data["languages"].update(detected_langs)

                if comb_match:
                    s_num = int(comb_match.group(1)) if comb_match.group(1) else 1
                    ep_str = f"S{s_num:02d}E{int(comb_match.group(2)):02d}-E{int(comb_match.group(3)):02d}"
                    p_data["combined_links"].append({**file_info, "ep": ep_str})
                elif ep_match:
                    s_num = int(ep_match.group(1)) if ep_match.group(1) else 1
                    e_num = int(ep_match.group(2))
                    ep_str = f"S{s_num:02d}E{e_num:02d}" if e_num < 100 else f"S{s_num:02d}E{e_num}"
                    p_data["episode_map"][ep_str][quality] = file_info
                else:
                    p_data["other_files"].append(file_info)

                new_caption = generate_caption_body(p_data)
                try:
                    await bot.edit_message_caption(
                        chat_id=int(target_channel),
                        message_id=int(p_data["msg_id"]),
                        caption=new_caption,
                        parse_mode=enums.ParseMode.HTML
                    )
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                    await bot.edit_message_caption(
                        chat_id=int(target_channel),
                        message_id=int(p_data["msg_id"]),
                        caption=new_caption,
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception as e:
                    logging.error(f"Error editing caption: {e}")
                return

            # CASE 2: Naya Post Bhejo
            # Poster: 100% Video File Thumbnail First
            poster_image = None
            if hasattr(media_obj, "thumbs") and media_obj.thumbs:
                try:
                    downloaded_thumb_path = await bot.download_media(media_obj.thumbs[0].file_id)
                    poster_image = downloaded_thumb_path
                except Exception as e:
                    logging.error(f"Thumb error: {e}")
                    poster_image = None

            if not poster_image:
                poster_image = DEFAULT_POSTER_URL

            # Post Data Store Setup
            post_data = {
                "msg_id": None,
                "title": f"{clean_title} ({year})" if year else clean_title,
                "kind": kind,
                "main_quality": main_quality,
                "languages": detected_langs,
                "episode_map": defaultdict(dict),
                "combined_links": [],
                "other_files": []
            }

            if comb_match:
                s_num = int(comb_match.group(1)) if comb_match.group(1) else 1
                ep_str = f"S{s_num:02d}E{int(comb_match.group(2)):02d}-E{int(comb_match.group(3)):02d}"
                post_data["combined_links"].append({**file_info, "ep": ep_str})
            elif ep_match:
                s_num = int(ep_match.group(1)) if ep_match.group(1) else 1
                e_num = int(ep_match.group(2))
                ep_str = f"S{s_num:02d}E{e_num:02d}" if e_num < 100 else f"S{s_num:02d}E{e_num}"
                post_data["episode_map"][ep_str][quality] = file_info
            else:
                post_data["other_files"].append(file_info)

            full_caption = generate_caption_body(post_data)

            sent_msg = None
            while True:
                try:
                    sent_msg = await bot.send_photo(
                        chat_id=int(target_channel),
                        photo=poster_image,
                        caption=full_caption,
                        parse_mode=enums.ParseMode.HTML,
                        has_spoiler=True
                    )
                    break
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                except Exception as e:
                    logging.error(f"Send photo error: {e}")
                    break

            if sent_msg:
                post_data["msg_id"] = sent_msg.id
                ACTIVE_POSTS[current_merge_key] = post_data

    except Exception as e:
        logging.error(f"Error in process_media_post: {e}")
    finally:
        if downloaded_thumb_path and os.path.exists(downloaded_thumb_path):
            try:
                os.remove(downloaded_thumb_path)
            except Exception:
                pass
  
