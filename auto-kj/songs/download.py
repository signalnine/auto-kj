import os
from yt_dlp import YoutubeDL


def download_song(youtube_id: str, cache_dir: str) -> dict:
    song_dir = os.path.join(cache_dir, youtube_id)
    os.makedirs(song_dir, exist_ok=True)

    ydl_opts = {
        "format": "best[height<=720]",
        "outtmpl": os.path.join(song_dir, "video.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    url = f"https://www.youtube.com/watch?v={youtube_id}"
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = info["requested_downloads"][0]["filepath"]

    return {
        "youtube_id": youtube_id,
        "title": info.get("title", "Unknown"),
        "artist": info.get("uploader", "Unknown"),
        "video_path": os.path.relpath(filepath, cache_dir),
    }
