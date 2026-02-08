import requests

LRCLIB_SEARCH = "https://lrclib.net/api/search"


def fetch_lyrics(title: str, artist: str = "") -> str | None:
    params = {"track_name": title}
    if artist:
        params["artist_name"] = artist
    try:
        resp = requests.get(LRCLIB_SEARCH, params=params, timeout=10)
        resp.raise_for_status()
        results = resp.json()
    except Exception:
        return None

    for r in results:
        synced = r.get("syncedLyrics")
        if synced:
            return synced
    return None


def save_lrc(content: str, path: str):
    with open(path, "w") as f:
        f.write(content)
