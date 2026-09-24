# --| This code created by: Jisshu_bots & SilentXBotz |--#
import re
import os
import hashlib
import asyncio
from info import *
from utils import *
from pyrogram import Client, filters, enums, errors
from database.users_chats_db import db
from database.ia_filterdb import save_file, unpack_new_file_id
import aiohttp
from typing import Optional
from collections import defaultdict

CAPTION_LANGUAGES = [
    "Bhojpuri",
    "Hindi",
    "Bengali",
    "Tamil",
    "English",
    "Bangla",
    "Telugu",
    "Malayalam",
    "Kannada",
    "Marathi",
    "Punjabi",
    "Bengali",
    "Gujrati",
    "Korean",
    "Gujarati",
    "Spanish",
    "French",
    "German",
    "Chinese",
    "Arabic",
    "Portuguese",
    "Russian",
    "Japanese",
    "Odia",
    "Assamese",
    "Urdu",
]

DEFAULT_POSTER_URL = "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"

UPDATE_CAPTION = """<blockquote>⚡️ <b>NEW {} ADDED</b></blockquote>

🎬 <b>Title:</b> <code>{}</code>
🎧 <b>Audio:</b> {}
📊 <b>Quality:</b> {}

<blockquote>📁 <b>Available Files & Links:</b>
{}</blockquote>
<blockquote>🔥 <b>Powered By</b> ➔ <a href='https://t.me/MzBotz'><b>𝐌𝐳𝐁𝐨𝐭𝐳™</b></a> ⚡️</blockquote>"""

movie_files = defaultdict(list)
debounce_tasks = {}
POST_DELAY = 10
update_queue = asyncio.Queue()
worker_task = None

media_filter = filters.document | filters.video | filters.audio


async def channel_post_worker(bot):
    """Background queue worker to avoid FloodWait and drop zero posts."""
    while True:
        try:
            file_name, files = await update_queue.get()
            await send_movie_update(bot, file_name, files)
            update_queue.task_done()
            await asyncio.sleep(2.5)  # Telegram-safe interval
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in channel_post_worker: {e}")
            await asyncio.sleep(2)


@Client.on_message(filters.chat(CHANNELS) & media_filter)
async def media(bot, message):
    global worker_task
    if worker_task is None or worker_task.done():
        worker_task = asyncio.create_task(channel_post_worker(bot))

    bot_id = bot.me.id
    media = getattr(message, message.media.value, None)
    if media and media.mime_type in ["video/mp4", "video/x-matroska", "document/mp4"]:
        media.file_type = message.media.value
        media.caption = message.caption
        success_sts = await save_file(media)
        if success_sts == "suc" and await db.get_send_movie_update_status(bot_id):
            await queue_movie_file(bot, media)


async def wait_and_dispatch(file_name):
    """Wait for remaining files of the same batch before sending to queue."""
    try:
        await asyncio.sleep(POST_DELAY)
        if file_name in movie_files:
            files_to_send = list(movie_files[file_name])
            del movie_files[file_name]
            await update_queue.put((file_name, files_to_send))
    except asyncio.CancelledError:
        pass
    finally:
        debounce_tasks.pop(file_name, None)


async def queue_movie_file(bot, media):
    try:
        file_name = await movie_name_format(media.file_name)
        caption = await movie_name_format(media.caption)
        year_match = re.search(r"\b(19|20)\d{2}\b", caption)
        year = year_match.group(0) if year_match else None
        season_match = re.search(r"(?i)(?:s|season)0*(\d{1,2})", caption) or re.search(
            r"(?i)(?:s|season)0*(\d{1,2})", file_name
        )
        if year:
            file_name = file_name[: file_name.find(year) + 4]
        elif season_match:
            season = season_match.group(1)
            file_name = file_name[: file_name.find(season) + 1]

        quality = await get_qualities(caption) or "HDRip"
        jisshuquality = await Jisshu_qualities(caption, media.file_name) or "720p"
        language = (
            ", ".join(
                [lang for lang in CAPTION_LANGUAGES if lang.lower() in caption.lower()]
            )
            or "Not Idea"
        )
        file_size_str = format_file_size(media.file_size)
        file_id, file_ref = unpack_new_file_id(media.file_id)

        thumb_obj = None
        if hasattr(media, "thumbs") and media.thumbs:
            thumb_obj = media.thumbs[0]

        movie_files[file_name].append(
            {
                "quality": quality,
                "jisshuquality": jisshuquality,
                "file_id": file_id,
                "file_size": file_size_str,
                "caption": caption,
                "raw_file_name": media.file_name,
                "language": language,
                "year": year,
                "thumb_obj": thumb_obj,
            }
        )

        # Dynamic Debounce to refresh batch timer
        if file_name in debounce_tasks:
            debounce_tasks[file_name].cancel()

        debounce_tasks[file_name] = asyncio.create_task(wait_and_dispatch(file_name))

    except Exception as e:
        print(f"Error in queue_movie_file: {e}")
        await bot.send_message(
            LOG_CHANNEL,
            f"Failed to queue movie file. Error - {e}\n\n<blockquote>If you don’t understand this error, you can ask in our support group: @Jisshu_support.</blockquote>",
        )


async def send_movie_update(bot, file_name, files):
    downloaded_thumb_path = None
    try:
        imdb_data = await get_imdb(file_name)
        title = imdb_data.get("title", file_name)

        year = files[0].get("year") or (imdb_data.get("year") if imdb_data else None)
        if not year:
            year_match = re.search(r"\b(19|20)\d{2}\b", file_name)
            year = year_match.group(0) if year_match else None

        # Poster priority: File Thumbnail > Online API > Default URL
        file_thumb_obj = next((f["thumb_obj"] for f in files if f.get("thumb_obj")), None)
        poster_image = None

        if file_thumb_obj:
            try:
                downloaded_thumb_path = await bot.download_media(file_thumb_obj.file_id)
                poster_image = downloaded_thumb_path
            except Exception as e:
                print(f"Thumb download failed: {e}")
                poster_image = None

        if not poster_image:
            online_poster = await fetch_movie_poster(title, year)
            poster_image = online_poster or DEFAULT_POSTER_URL

        kind = imdb_data.get("kind", "").strip().upper().replace(" ", "_") if imdb_data else ""
        if kind == "TV_SERIES":
            kind = "SERIES"
        elif not kind:
            is_series = bool(
                re.search(r"(?i)(?:s|season|e|ep|episode|\b\d{1,4}-\d{1,4}\b)", file_name)
                or len(files) > 1
            )
            kind = "SERIES" if is_series else "MOVIE"

        languages = set()
        for file in files:
            if file["language"] != "Not Idea":
                languages.update(file["language"].split(", "))
        language = ", ".join(sorted(languages)) or "Not Idea"

        # Regex support for S01E01, [E01-E45], E01-E200, EP01-EP300
        episode_pattern = re.compile(r"S(\d{1,2})[\s_\[\-]*E(?:P)?(\d{1,4})", re.IGNORECASE)
        combined_pattern = re.compile(
            r"(?:S(\d{1,2}))?[\s_\[\-]*E(?:P)?(\d{1,4})\s*[-~to]+\s*E?(?:P)?(\d{1,4})[\]\s_]*",
            re.IGNORECASE,
        )

        episode_map = defaultdict(dict)
        combined_links = []

        for file in files:
            caption = file.get("caption") or ""
            raw_name = file.get("raw_file_name") or ""
            check_text = f"{caption} {raw_name} {file_name}".strip()

            quality = file.get("jisshuquality") or file.get("quality") or "Unknown"
            file_id = file["file_id"]
            size = file.get("file_size", "")

            combined_match = combined_pattern.search(check_text)
            match = episode_pattern.search(check_text)

            if combined_match:
                s_num = int(combined_match.group(1)) if combined_match.group(1) else 1
                season = f"S{s_num:02d}"
                start_ep = int(combined_match.group(2))
                end_ep = int(combined_match.group(3))
                ep = f"{season}E{start_ep:02d}-E{end_ep:02d}"

                size_str = f" [<code>{size}</code>]" if size else ""
                combined_links.append(
                    f"📦 {ep} ({quality}){size_str} : <a href='https://t.me/{temp.U_NAME}?start=file_0_{file_id}'>📥 Download</a>"
                )
            elif match:
                ep = f"S{int(match.group(1)):02d}E{int(match.group(2)):02d}"
                episode_map[ep][quality] = file
            elif re.search(r"complete|completed|batch|combined", check_text, re.IGNORECASE):
                size_str = f" [<code>{size}</code>]" if size else ""
                combined_links.append(
                    f"📦 Combined ({quality}){size_str} : <a href='https://t.me/{temp.U_NAME}?start=file_0_{file_id}'>📥 Download</a>"
                )

        quality_text = ""

        for ep, qualities in sorted(episode_map.items()):
            parts = []
            for quality in sorted(qualities.keys()):
                f = qualities[quality]
                size_str = f" [<code>{f['file_size']}</code>]" if f.get("file_size") else ""
                part = f"<a href='https://t.me/{temp.U_NAME}?start=file_0_{f['file_id']}'>📥 Download ({quality})</a>{size_str}"
                parts.append(part)
            joined = " - ".join(parts)
            quality_text += f"📦 {ep} : {joined}\n"

        if combined_links:
            quality_text += "\n<b>COMBiNED</b> ✅\n\n"
            quality_text += "\n".join(combined_links) + "\n"

        if not quality_text:
            quality_groups = defaultdict(list)
            for file in files:
                quality = file.get("jisshuquality") or file.get("quality") or "Unknown"
                quality_groups[quality].append(file)

            for quality, q_files in sorted(quality_groups.items()):
                links = [
                    f"<a href='https://t.me/{temp.U_NAME}?start=file_0_{f['file_id']}'>📥 Download</a> [<code>{f.get('file_size', '')}</code>]"
                    for f in q_files
                ]
                line = f"📦 <b>{quality}</b> : " + " | ".join(links)
                quality_text += line + "\n"

        clean_year = f" ({year})" if year else ""
        final_title = f"{title}{clean_year}"

        full_caption = UPDATE_CAPTION.format(kind, final_title, language, files[0]["quality"], quality_text)

        movie_update_channel = await db.movies_update_channel_id()
        target_chat_id = movie_update_channel if movie_update_channel else MOVIE_UPDATE_CHANNEL

        # Send with auto FloodWait retry
        while True:
            try:
                await bot.send_photo(
                    chat_id=target_chat_id,
                    photo=poster_image,
                    caption=full_caption,
                    parse_mode=enums.ParseMode.HTML,
                )
                break
            except errors.FloodWait as fw:
                print(f"FloodWait encountered: Sleeping for {fw.value} seconds...")
                await asyncio.sleep(fw.value)
            except Exception as e:
                print(f"Error while sending photo: {e}")
                break

    except Exception as e:
        print("Failed to send movie update. Error - ", e)
        await bot.send_message(
            LOG_CHANNEL,
            f"Failed to send movie update. Error - {e}\n\n<blockquote>If you don’t understand this error, you can ask in our support group: @Jisshu_support.</blockquote>",
        )
    finally:
        if downloaded_thumb_path and os.path.exists(downloaded_thumb_path):
            try:
                os.remove(downloaded_thumb_path)
            except Exception:
                pass


async def get_imdb(file_name):
    try:
        formatted_name = await movie_name_format(file_name)
        imdb = await get_poster(formatted_name)
        if not imdb:
            return {}
        return {
            "title": imdb.get("title", formatted_name),
            "kind": imdb.get("kind", "Movie"),
            "year": imdb.get("year"),
            "url": imdb.get("url"),
        }
    except Exception as e:
        print(f"IMDB fetch error: {e}")
        return {}


async def fetch_movie_poster(title: str, year: Optional[int] = None) -> Optional[str]:
    async with aiohttp.ClientSession() as session:
        query = title.strip().replace(" ", "+")
        if year:
            query += f"+{year}"
        url = f"https://jisshuapis.vercel.app/api.php?query={query}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as res:
                if res.status != 200:
                    return None
                data = await res.json()

                for key in ["jisshu-2", "jisshu-3", "jisshu-4"]:
                    posters = data.get(key)
                    if posters and isinstance(posters, list) and posters:
                        return posters[0]
                return None
        except Exception:
            return None


def generate_unique_id(movie_name):
    return hashlib.md5(movie_name.encode("utf-8")).hexdigest()[:5]


async def get_qualities(text):
    qualities = [
        "480p", "720p", "720p HEVC", "1080p", "ORG", "org", "hdcam", "HDCAM",
        "HQ", "hq", "HDRip", "hdrip", "camrip", "WEB-DL", "CAMRip", "hdtc",
        "predvd", "DVDscr", "dvdscr", "dvdrip", "HDTC", "dvdscreen", "HDTS", "hdts",
    ]
    found_qualities = [q for q in qualities if q.lower() in text.lower()]
    return ", ".join(found_qualities) or "HDRip"


async def Jisshu_qualities(text, file_name):
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


async def movie_name_format(file_name):
    filename = re.sub(
        r"http\S+",
        "",
        re.sub(r"@\w+|#\w+", "", file_name)
        .replace("_", " ")
        .replace("[", "")
        .replace("]", "")
        .replace("(", "")
        .replace(")", "")
        .replace("{", "")
        .replace("}", "")
        .replace(".", " ")
        .replace("@", "")
        .replace(":", "")
        .replace(";", "")
        .replace("'", "")
        .replace("-", "")
        .replace("!", ""),
    ).strip()
    return filename


def format_file_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"
