import os
import time
import json
import subprocess
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SOURCES_FILE = "sources.txt"
POSTED_FILE = "posted.json"
DOWNLOAD_DIR = "downloads"

MAX_VIDEO_AGE_DAYS = 1
VIDEOS_TO_CHECK_PER_ACCOUNT = 10
CHECK_EVERY_SECONDS = 60

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()

    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except:
        return set()


def save_posted(posted):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(posted), f, indent=2)


def load_sources():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def run_ytdlp_json(video_url):
    command = [
        "python", "-m", "yt_dlp",
        "--dump-json",
        video_url
    ]

    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        print("Could not read video info:", result.stderr)
        return None

    return json.loads(result.stdout)


def get_video_timestamp(info):
    timestamp = info.get("timestamp")

    if timestamp:
        return int(timestamp)

    upload_date = info.get("upload_date")

    if upload_date:
        upload_time = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
        return int(upload_time.timestamp())

    return 0


def is_recent_video(info):
    video_timestamp = get_video_timestamp(info)

    if video_timestamp == 0:
        return False

    upload_time = datetime.fromtimestamp(video_timestamp, timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_VIDEO_AGE_DAYS)

    return upload_time >= cutoff


def find_latest_videos(source_url):
    command = [
        "python", "-m", "yt_dlp",
        "--flat-playlist",
        "--print", "%(webpage_url)s",
        source_url
    ]

    result = subprocess.run(command, capture_output=True, text=True)

    links = []

    for line in result.stdout.splitlines():
        if line.startswith("http"):
            links.append(line.strip())

    videos = []

    for video_url in links[:VIDEOS_TO_CHECK_PER_ACCOUNT]:
        info = run_ytdlp_json(video_url)

        if not info:
            continue

        if not is_recent_video(info):
            print("Skipping old video:", video_url)
            continue

        timestamp = get_video_timestamp(info)

        videos.append({
            "url": video_url,
            "info": info,
            "timestamp": timestamp
        })

    videos.sort(key=lambda x: x["timestamp"], reverse=True)

    return videos


def download_video(video_url):
    command = [
        "python", "-m", "yt_dlp",
        "-f", "mp4/best",
        "-o", f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        video_url
    ]

    subprocess.run(command, check=True)

    files = [
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if f.endswith((".mp4", ".webm", ".mov"))
    ]

    if not files:
        return None

    return max(files, key=os.path.getctime)


def make_caption(info, video_url):
    uploader = info.get("uploader") or info.get("channel") or "unknown"
    title = info.get("title") or "No caption found"
    link = info.get("webpage_url") or video_url

    if not uploader.startswith("@"):
        uploader = f"@{uploader}"

    caption = (
        f"Streamer: {uploader}\n\n"
        f"Caption:\n{title}\n\n"
        f"Source:\n{link}"
    )

    return caption[:1024]


def post_to_telegram(video_path, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"

    with open(video_path, "rb") as video:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "caption": caption,
                "supports_streaming": True
            },
            files={"video": video}
        )

    print(response.text)


def clean_downloads():
    for file in os.listdir(DOWNLOAD_DIR):
        os.remove(os.path.join(DOWNLOAD_DIR, file))


print("Bot started...")

while True:
    posted = load_posted()
    sources = load_sources()

    for source in sources:
        print("Checking account:", source)

        try:
            videos = find_latest_videos(source)

            for video in videos:
                video_url = video["url"]
                info = video["info"]

                if video_url in posted:
                    print("Already posted:", video_url)
                    continue

                print("Posting recent video:", video_url)

                video_path = download_video(video_url)

                if video_path:
                    caption = make_caption(info, video_url)

                    post_to_telegram(video_path, caption)

                    posted.add(video_url)
                    save_posted(posted)
                    clean_downloads()

        except Exception as e:
            print("Error:", e)

    print("Waiting 1 minute...")
    time.sleep(CHECK_EVERY_SECONDS)
