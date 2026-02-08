from yt_dlp import YoutubeDL

KARAOKE_KEYWORDS = ["karaoke", "sing along", "singalong", "lyrics", "instrumental"]
KARAOKE_THRESHOLD = 1


def score_karaoke_result(entry: dict) -> int:
    title = entry.get("title", "").lower()
    return sum(1 for kw in KARAOKE_KEYWORDS if kw in title)


def search_song(query: str) -> dict | None:
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}

    # Try karaoke search first
    with YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch5:{query} karaoke", download=False)
        except Exception:
            info = {"entries": []}
        entries = info.get("entries") or []
        scored = [(score_karaoke_result(e), e) for e in entries]
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] >= KARAOKE_THRESHOLD:
            best = scored[0][1]
            best["is_karaoke"] = True
            return best

    # Fall back to regular search
    with YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch3:{query}", download=False)
        except Exception:
            info = {"entries": []}
        entries = info.get("entries") or []
        if entries:
            best = entries[0]
            best["is_karaoke"] = False
            return best

    return None
