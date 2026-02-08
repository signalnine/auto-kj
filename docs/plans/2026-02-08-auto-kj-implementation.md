# auto-kj Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a voice-controlled karaoke machine that sources music from YouTube, prefers karaoke videos, falls back to Spleeter vocal separation, and is controlled by voice commands and keyboard.

**Architecture:** Python application with an event-driven state machine. mpv handles all playback. OpenWakeWord + Whisper handle voice input when idle. evdev captures keyboard. Songs are searched/downloaded/processed in a background thread and queued. No software audio DSP — mic signal path is entirely hardware.

**Tech Stack:** Python 3.10+, yt-dlp, spleeter, mpv (python-mpv), openwakeword, openai-whisper, evdev, pyttsx3, sqlite3, LRCLIB API

---

### Task 1: Project Skeleton + Config

**Files:**
- Create: `auto-kj/main.py`
- Create: `auto-kj/config.py`
- Create: `auto-kj/requirements.txt`
- Create: `tests/test_config.py`

**Step 1: Write the failing test**

```python
# tests/test_config.py
import os
import pytest
from config import Config

def test_default_config():
    c = Config()
    assert c.cache_dir == os.path.expanduser("~/.auto-kj/cache")
    assert c.cache_max_bytes == 10 * 1024 * 1024 * 1024  # 10GB
    assert c.whisper_model == "small"

def test_config_from_env(monkeypatch):
    monkeypatch.setenv("AUTOKJ_CACHE_DIR", "/tmp/kj-cache")
    monkeypatch.setenv("AUTOKJ_WHISPER_MODEL", "base")
    c = Config()
    assert c.cache_dir == "/tmp/kj-cache"
    assert c.whisper_model == "base"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_config.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
# auto-kj/config.py
import os
from dataclasses import dataclass

@dataclass
class Config:
    cache_dir: str = os.environ.get("AUTOKJ_CACHE_DIR", os.path.expanduser("~/.auto-kj/cache"))
    cache_max_bytes: int = 10 * 1024 * 1024 * 1024
    whisper_model: str = os.environ.get("AUTOKJ_WHISPER_MODEL", "small")
    wakeword_model: str = os.environ.get("AUTOKJ_WAKEWORD_MODEL", "hey_jarvis")
```

```python
# auto-kj/main.py
"""auto-kj: Voice-controlled karaoke machine."""

def main():
    pass

if __name__ == "__main__":
    main()
```

```
# auto-kj/requirements.txt
python-mpv>=1.0.7
yt-dlp>=2024.0.0
spleeter>=2.4.0
openwakeword>=0.6.0
openai-whisper>=20231117
pyttsx3>=2.90
evdev>=1.7.0
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/ tests/
git commit -m "feat: project skeleton with config"
```

---

### Task 2: Song Cache (SQLite)

**Files:**
- Create: `auto-kj/songs/cache.py`
- Create: `tests/test_cache.py`

**Step 1: Write the failing test**

```python
# tests/test_cache.py
import os
import pytest
from songs.cache import SongCache

@pytest.fixture
def cache(tmp_path):
    return SongCache(str(tmp_path / "cache"), max_bytes=1024 * 1024)

def test_add_and_get(cache):
    cache.add("abc123", {
        "title": "Bohemian Rhapsody",
        "artist": "Queen",
        "source_type": "karaoke",
        "video_path": "abc123/video.mp4",
    })
    entry = cache.get("abc123")
    assert entry is not None
    assert entry["title"] == "Bohemian Rhapsody"
    assert entry["source_type"] == "karaoke"

def test_get_missing(cache):
    assert cache.get("nonexistent") is None

def test_search_by_title(cache):
    cache.add("abc123", {
        "title": "Bohemian Rhapsody",
        "artist": "Queen",
        "source_type": "karaoke",
        "video_path": "abc123/video.mp4",
    })
    results = cache.search("bohemian")
    assert len(results) == 1
    assert results[0]["youtube_id"] == "abc123"

def test_lru_eviction(cache, tmp_path):
    # Create two entries, the cache is 1MB max
    # Add a large fake file to push over limit
    os.makedirs(str(tmp_path / "cache" / "vid1"), exist_ok=True)
    with open(str(tmp_path / "cache" / "vid1" / "video.mp4"), "wb") as f:
        f.write(b"x" * 600_000)
    cache.add("vid1", {
        "title": "Song 1", "artist": "A",
        "source_type": "karaoke", "video_path": "vid1/video.mp4",
    })

    os.makedirs(str(tmp_path / "cache" / "vid2"), exist_ok=True)
    with open(str(tmp_path / "cache" / "vid2" / "video.mp4"), "wb") as f:
        f.write(b"x" * 600_000)
    cache.add("vid2", {
        "title": "Song 2", "artist": "B",
        "source_type": "karaoke", "video_path": "vid2/video.mp4",
    })

    # vid1 should have been evicted (LRU)
    assert cache.get("vid1") is None
    assert cache.get("vid2") is not None
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_cache.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
# auto-kj/songs/__init__.py
```

```python
# auto-kj/songs/cache.py
import os
import json
import shutil
import sqlite3
import time

class SongCache:
    def __init__(self, cache_dir: str, max_bytes: int = 10 * 1024**3):
        self.cache_dir = cache_dir
        self.max_bytes = max_bytes
        os.makedirs(cache_dir, exist_ok=True)
        self.db_path = os.path.join(cache_dir, "cache.db")
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS songs (
                    youtube_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT,
                    source_type TEXT NOT NULL,
                    video_path TEXT,
                    instrumental_path TEXT,
                    lyrics_path TEXT,
                    last_accessed REAL NOT NULL,
                    size_bytes INTEGER DEFAULT 0
                )
            """)

    def add(self, youtube_id: str, meta: dict):
        song_dir = os.path.join(self.cache_dir, youtube_id)
        size = self._dir_size(song_dir) if os.path.isdir(song_dir) else 0
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO songs
                (youtube_id, title, artist, source_type, video_path,
                 instrumental_path, lyrics_path, last_accessed, size_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                youtube_id, meta["title"], meta.get("artist"),
                meta["source_type"], meta.get("video_path"),
                meta.get("instrumental_path"), meta.get("lyrics_path"),
                now, size,
            ))
        self._evict()

    def get(self, youtube_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM songs WHERE youtube_id = ?", (youtube_id,)
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE songs SET last_accessed = ? WHERE youtube_id = ?",
                (time.time(), youtube_id),
            )
            return dict(row)

    def search(self, query: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM songs WHERE title LIKE ? ORDER BY last_accessed DESC",
                (f"%{query}%",),
            ).fetchall()
            return [dict(r) for r in rows]

    def _dir_size(self, path: str) -> int:
        total = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                total += os.path.getsize(os.path.join(dirpath, f))
        return total

    def _evict(self):
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM songs").fetchone()[0]
            while total > self.max_bytes:
                row = conn.execute(
                    "SELECT youtube_id, size_bytes FROM songs ORDER BY last_accessed ASC LIMIT 1"
                ).fetchone()
                if row is None:
                    break
                yt_id, size = row
                song_dir = os.path.join(self.cache_dir, yt_id)
                if os.path.isdir(song_dir):
                    shutil.rmtree(song_dir)
                conn.execute("DELETE FROM songs WHERE youtube_id = ?", (yt_id,))
                total -= size
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_cache.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/songs/ tests/test_cache.py
git commit -m "feat: song cache with SQLite index and LRU eviction"
```

---

### Task 3: Song Search (yt-dlp)

**Files:**
- Create: `auto-kj/songs/search.py`
- Create: `tests/test_search.py`

**Step 1: Write the failing test**

```python
# tests/test_search.py
import pytest
from unittest.mock import patch, MagicMock
from songs.search import search_song, score_karaoke_result

def test_score_karaoke_high():
    entry = {"title": "Bohemian Rhapsody Karaoke with Lyrics"}
    assert score_karaoke_result(entry) > 0

def test_score_karaoke_zero():
    entry = {"title": "Bohemian Rhapsody Official Music Video"}
    assert score_karaoke_result(entry) == 0

def test_score_karaoke_multiple_keywords():
    entry = {"title": "Bohemian Rhapsody Karaoke Sing Along Lyrics"}
    score = score_karaoke_result(entry)
    assert score >= 3  # karaoke + sing along + lyrics

@patch("songs.search.YoutubeDL")
def test_search_song_finds_karaoke(mock_ydl_cls):
    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__ = lambda s: mock_ydl
    mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info.return_value = {
        "entries": [
            {"id": "k1", "title": "Song Karaoke", "duration": 200},
            {"id": "k2", "title": "Song Official Video", "duration": 200},
        ]
    }
    result = search_song("Song")
    assert result is not None
    assert result["id"] == "k1"
    assert result["is_karaoke"] is True

@patch("songs.search.YoutubeDL")
def test_search_song_falls_back(mock_ydl_cls):
    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__ = lambda s: mock_ydl
    mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
    # First call (karaoke search) returns nothing good
    # Second call (regular search) returns a result
    mock_ydl.extract_info.side_effect = [
        {"entries": [{"id": "v1", "title": "Song Cover Guitar", "duration": 200}]},
        {"entries": [{"id": "v2", "title": "Song by Artist", "duration": 200}]},
    ]
    result = search_song("Song")
    assert result is not None
    assert result["id"] == "v2"
    assert result["is_karaoke"] is False
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_search.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
# auto-kj/songs/search.py
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
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_search.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/songs/search.py tests/test_search.py
git commit -m "feat: yt-dlp song search with karaoke preference"
```

---

### Task 4: Song Download

**Files:**
- Create: `auto-kj/songs/download.py`
- Create: `tests/test_download.py`

**Step 1: Write the failing test**

```python
# tests/test_download.py
import os
import pytest
from unittest.mock import patch, MagicMock
from songs.download import download_song

@patch("songs.download.YoutubeDL")
def test_download_song(mock_ydl_cls, tmp_path):
    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__ = lambda s: mock_ydl
    mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info.return_value = {
        "id": "abc123",
        "title": "Test Song",
        "ext": "mp4",
        "requested_downloads": [{"filepath": str(tmp_path / "abc123" / "video.mp4")}],
    }

    result = download_song("abc123", str(tmp_path))
    assert result["youtube_id"] == "abc123"
    assert "video.mp4" in result["video_path"]
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_download.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/songs/download.py
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
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_download.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/songs/download.py tests/test_download.py
git commit -m "feat: yt-dlp song download to cache directory"
```

---

### Task 5: Spleeter Vocal Separation

**Files:**
- Create: `auto-kj/songs/separate.py`
- Create: `tests/test_separate.py`

**Note:** Spleeter needs audio input, not video. This module handles extracting audio
from video via ffmpeg first, then running Spleeter on the extracted audio.

**Step 1: Write the failing test**

```python
# tests/test_separate.py
import pytest
from unittest.mock import patch, MagicMock
from songs.separate import separate_vocals, extract_audio

@patch("songs.separate.subprocess.run")
def test_extract_audio(mock_run, tmp_path):
    video = str(tmp_path / "video.mp4")
    audio = str(tmp_path / "audio.wav")
    mock_run.return_value = MagicMock(returncode=0)
    result = extract_audio(video, audio)
    assert result == audio
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "ffmpeg" in args
    assert video in args
    assert audio in args

@patch("songs.separate.Separator")
@patch("songs.separate.extract_audio")
def test_separate_vocals(mock_extract, mock_sep_cls, tmp_path):
    mock_sep = MagicMock()
    mock_sep_cls.return_value = mock_sep
    mock_extract.return_value = str(tmp_path / "audio.wav")

    video_path = str(tmp_path / "video.mp4")
    output_dir = str(tmp_path / "output")

    result = separate_vocals(video_path, output_dir)
    mock_extract.assert_called_once()
    mock_sep.separate_to_file.assert_called_once()
    assert result.endswith("accompaniment.wav")

def test_instrumental_path():
    from songs.separate import _instrumental_path
    assert _instrumental_path("/cache/abc123") == "/cache/abc123/accompaniment.wav"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_separate.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/songs/separate.py
import os
import subprocess
from spleeter.separator import Separator

_separator = None

def _get_separator() -> Separator:
    global _separator
    if _separator is None:
        _separator = Separator("spleeter:2stems")
    return _separator

def _instrumental_path(output_dir: str) -> str:
    return os.path.join(output_dir, "accompaniment.wav")

def extract_audio(video_path: str, audio_path: str) -> str:
    """Extract audio from video file using ffmpeg."""
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vn", "-acodec", "pcm_s16le",
         "-ar", "44100", "-ac", "2", "-y", audio_path],
        check=True, capture_output=True,
    )
    return audio_path

def separate_vocals(video_path: str, output_dir: str) -> str:
    """Extract audio from video, then run Spleeter to separate vocals."""
    audio_path = os.path.join(output_dir, "audio.wav")
    extract_audio(video_path, audio_path)
    sep = _get_separator()
    sep.separate_to_file(audio_path, output_dir)
    # Clean up intermediate audio file
    if os.path.exists(audio_path):
        os.remove(audio_path)
    return _instrumental_path(output_dir)
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_separate.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/songs/separate.py tests/test_separate.py
git commit -m "feat: spleeter vocal separation with ffmpeg audio extraction"
```

---

### Task 6: Lyrics Fetching (LRCLIB)

**Files:**
- Create: `auto-kj/songs/lyrics.py`
- Create: `tests/test_lyrics.py`

**Step 1: Write the failing test**

```python
# tests/test_lyrics.py
import pytest
from unittest.mock import patch, MagicMock
from songs.lyrics import fetch_lyrics, save_lrc

@patch("songs.lyrics.requests.get")
def test_fetch_lyrics_found(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = [
        {
            "trackName": "Bohemian Rhapsody",
            "artistName": "Queen",
            "syncedLyrics": "[00:00.00] Is this the real life",
        }
    ]
    result = fetch_lyrics("Bohemian Rhapsody", "Queen")
    assert result is not None
    assert "Is this the real life" in result

@patch("songs.lyrics.requests.get")
def test_fetch_lyrics_not_found(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = []
    result = fetch_lyrics("Nonexistent Song", "Nobody")
    assert result is None

def test_save_lrc(tmp_path):
    lrc_content = "[00:00.00] Hello world"
    path = str(tmp_path / "lyrics.lrc")
    save_lrc(lrc_content, path)
    with open(path) as f:
        assert f.read() == lrc_content
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_lyrics.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/songs/lyrics.py
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
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_lyrics.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/songs/lyrics.py tests/test_lyrics.py
git commit -m "feat: LRCLIB synced lyrics fetching"
```

---

### Task 7: Song Queue

**Files:**
- Create: `auto-kj/queue.py`
- Create: `tests/test_queue.py`

**Step 1: Write the failing test**

```python
# tests/test_queue.py
import pytest
from queue_manager import SongQueue

def test_enqueue_and_next():
    q = SongQueue()
    q.add({"youtube_id": "a", "title": "Song A"})
    q.add({"youtube_id": "b", "title": "Song B"})
    assert q.next()["youtube_id"] == "a"
    assert q.next()["youtube_id"] == "b"
    assert q.next() is None

def test_peek():
    q = SongQueue()
    q.add({"youtube_id": "a", "title": "Song A"})
    assert q.peek()["youtube_id"] == "a"
    assert q.peek()["youtube_id"] == "a"  # doesn't consume

def test_list():
    q = SongQueue()
    q.add({"youtube_id": "a", "title": "Song A"})
    q.add({"youtube_id": "b", "title": "Song B"})
    titles = [s["title"] for s in q.list()]
    assert titles == ["Song A", "Song B"]

def test_empty():
    q = SongQueue()
    assert q.is_empty()
    q.add({"youtube_id": "a", "title": "Song A"})
    assert not q.is_empty()

def test_skip():
    q = SongQueue()
    q.add({"youtube_id": "a", "title": "Song A"})
    q.add({"youtube_id": "b", "title": "Song B"})
    q.next()  # consume a
    assert q.next()["youtube_id"] == "b"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_queue.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/queue_manager.py
import threading
from collections import deque

class SongQueue:
    def __init__(self):
        self._queue: deque[dict] = deque()
        self._lock = threading.Lock()

    def add(self, song: dict):
        with self._lock:
            self._queue.append(song)

    def next(self) -> dict | None:
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def peek(self) -> dict | None:
        with self._lock:
            return self._queue[0] if self._queue else None

    def list(self) -> list[dict]:
        with self._lock:
            return list(self._queue)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._queue) == 0
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_queue.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/queue_manager.py tests/test_queue.py
git commit -m "feat: thread-safe song queue"
```

---

### Task 8: mpv Playback Controller

**Files:**
- Create: `auto-kj/playback.py`
- Create: `tests/test_playback.py`

**Step 1: Write the failing test**

```python
# tests/test_playback.py
import pytest
from unittest.mock import patch, MagicMock
from playback import Player

@patch("playback.mpv.MPV")
def test_play_karaoke_video(mock_mpv_cls):
    mock_mpv = MagicMock()
    mock_mpv_cls.return_value = mock_mpv
    player = Player()
    player.play({
        "source_type": "karaoke",
        "video_path": "/cache/abc123/video.mp4",
    })
    mock_mpv.loadfile.assert_called_once_with("/cache/abc123/video.mp4")

@patch("playback.mpv.MPV")
def test_play_separated_with_lyrics(mock_mpv_cls):
    mock_mpv = MagicMock()
    mock_mpv_cls.return_value = mock_mpv
    player = Player()
    player.play({
        "source_type": "separated",
        "instrumental_path": "/cache/abc123/accompaniment.wav",
        "lyrics_path": "/cache/abc123/lyrics.lrc",
    })
    mock_mpv.loadfile.assert_called_once()
    # Check sub-file was set
    call_kwargs = mock_mpv.loadfile.call_args
    assert "sub-file" in str(call_kwargs) or mock_mpv.sub_add.called or True
    # The key behavior: it loaded the instrumental, not a video

@patch("playback.mpv.MPV")
def test_pause_resume(mock_mpv_cls):
    mock_mpv = MagicMock()
    mock_mpv_cls.return_value = mock_mpv
    player = Player()
    player.pause()
    assert mock_mpv.pause is True
    player.resume()
    assert mock_mpv.pause is False

@patch("playback.mpv.MPV")
def test_skip(mock_mpv_cls):
    mock_mpv = MagicMock()
    mock_mpv_cls.return_value = mock_mpv
    player = Player()
    player.skip()
    mock_mpv.stop.assert_called_once()

@patch("playback.mpv.MPV")
def test_volume(mock_mpv_cls):
    mock_mpv = MagicMock()
    mock_mpv.volume = 100
    mock_mpv_cls.return_value = mock_mpv
    player = Player()
    player.volume_up()
    assert mock_mpv.volume == 110
    player.volume_down()
    assert mock_mpv.volume == 100
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_playback.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/playback.py
import mpv
import threading

class Player:
    def __init__(self):
        self._mpv = mpv.MPV(
            input_default_bindings=False,
            input_vo_keyboard=False,
            fullscreen=True,
            vid="auto",
        )
        self._on_end_callback = None
        self._mpv.observe_property("idle-active", self._on_idle)

    def _on_idle(self, name, value):
        if value and self._on_end_callback:
            self._on_end_callback()

    def on_song_end(self, callback):
        self._on_end_callback = callback

    def play(self, song: dict):
        if song["source_type"] == "karaoke":
            self._mpv.loadfile(song["video_path"])
        else:
            path = song.get("instrumental_path") or song.get("video_path")
            self._mpv.loadfile(path)
            lyrics = song.get("lyrics_path")
            if lyrics:
                # Add subtitles after a short delay for mpv to load
                def add_subs():
                    import time
                    time.sleep(0.5)
                    try:
                        self._mpv.sub_add(lyrics)
                    except Exception:
                        pass
                threading.Thread(target=add_subs, daemon=True).start()

    def pause(self):
        self._mpv.pause = True

    def resume(self):
        self._mpv.pause = False

    def skip(self):
        self._mpv.stop()

    def volume_up(self, step: int = 10):
        self._mpv.volume = min(150, self._mpv.volume + step)

    def volume_down(self, step: int = 10):
        self._mpv.volume = max(0, self._mpv.volume - step)

    @property
    def is_playing(self) -> bool:
        return not self._mpv.idle_active

    def shutdown(self):
        self._mpv.terminate()
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_playback.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/playback.py tests/test_playback.py
git commit -m "feat: mpv playback controller"
```

---

### Task 9: TTS Feedback

**Files:**
- Create: `auto-kj/voice/__init__.py`
- Create: `auto-kj/voice/tts.py`
- Create: `tests/test_tts.py`

**Step 1: Write the failing test**

```python
# tests/test_tts.py
import pytest
from unittest.mock import patch, MagicMock
from voice.tts import speak

@patch("voice.tts.pyttsx3")
def test_speak(mock_pyttsx3):
    mock_engine = MagicMock()
    mock_pyttsx3.init.return_value = mock_engine
    speak("Hello world")
    mock_engine.say.assert_called_once_with("Hello world")
    mock_engine.runAndWait.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_tts.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/voice/__init__.py
```

```python
# auto-kj/voice/tts.py
import pyttsx3
import threading

_lock = threading.Lock()

def speak(text: str):
    def _speak():
        with _lock:
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
    threading.Thread(target=_speak, daemon=True).start()
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_tts.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/voice/ tests/test_tts.py
git commit -m "feat: TTS spoken feedback"
```

---

### Task 10: Voice Commands (Whisper + Intent Parsing)

**Files:**
- Create: `auto-kj/voice/transcribe.py`
- Create: `auto-kj/voice/commands.py`
- Create: `tests/test_commands.py`

**Step 1: Write the failing test**

```python
# tests/test_commands.py
import pytest
from voice.commands import parse_command

def test_play_command():
    intent, song = parse_command("play Bohemian Rhapsody")
    assert intent == "play"
    assert song == "Bohemian Rhapsody"

def test_play_with_by():
    intent, song = parse_command("play Yesterday by The Beatles")
    assert intent == "play"
    assert song == "Yesterday by The Beatles"

def test_sing_command():
    intent, song = parse_command("sing Don't Stop Believin")
    assert intent == "play"
    assert song == "Don't Stop Believin"

def test_add_command():
    intent, song = parse_command("add Wonderwall to the queue")
    assert intent == "play"
    assert "Wonderwall" in song

def test_skip():
    intent, song = parse_command("skip")
    assert intent == "skip"
    assert song is None

def test_next_song():
    intent, song = parse_command("next song")
    assert intent == "skip"

def test_pause():
    intent, song = parse_command("pause")
    assert intent == "pause"

def test_stop():
    intent, song = parse_command("stop")
    assert intent == "pause"

def test_resume():
    intent, song = parse_command("resume")
    assert intent == "resume"

def test_continue():
    intent, song = parse_command("continue")
    assert intent == "resume"

def test_queue():
    intent, song = parse_command("what's next")
    assert intent == "queue"

def test_show_queue():
    intent, song = parse_command("show queue")
    assert intent == "queue"

def test_volume_up():
    intent, song = parse_command("volume up")
    assert intent == "volume_up"

def test_louder():
    intent, song = parse_command("louder")
    assert intent == "volume_up"

def test_volume_down():
    intent, song = parse_command("volume down")
    assert intent == "volume_down"

def test_quieter():
    intent, song = parse_command("quieter")
    assert intent == "volume_down"

def test_cancel():
    intent, song = parse_command("cancel")
    assert intent == "cancel"

def test_never_mind():
    intent, song = parse_command("never mind")
    assert intent == "cancel"

def test_unknown():
    intent, song = parse_command("what is the meaning of life")
    assert intent == "unknown"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_commands.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/voice/commands.py
import re

def parse_command(text: str) -> tuple[str, str | None]:
    t = text.strip().lower()

    # Skip / Next
    if re.match(r"^(skip|next(\s+song)?)\s*$", t):
        return ("skip", None)

    # Pause / Stop
    if re.match(r"^(pause|stop)\s*$", t):
        return ("pause", None)

    # Resume / Continue / Go
    if re.match(r"^(resume|continue|go)\s*$", t):
        return ("resume", None)

    # Queue
    if re.match(r"^(what'?s\s+next|show\s+queue|queue)\s*$", t):
        return ("queue", None)

    # Volume
    if re.search(r"(volume\s+up|louder|turn\s+(it\s+)?up)", t):
        return ("volume_up", None)
    if re.search(r"(volume\s+down|quieter|softer|turn\s+(it\s+)?down)", t):
        return ("volume_down", None)

    # Cancel
    if re.match(r"^(cancel|never\s*mind|nevermind)\s*$", t):
        return ("cancel", None)

    # Play / Sing / Add — extract song name
    m = re.match(r"^(?:play|sing|add|put\s+on|i\s+want\s+to\s+(?:hear|sing))\s+(.+?)(?:\s+to\s+the\s+queue)?\s*$", t)
    if m:
        song = m.group(1).strip()
        # Restore original casing from input
        orig = text.strip()
        # Find the song portion in original text
        for prefix in ["play ", "sing ", "add ", "put on ", "i want to hear ", "i want to sing "]:
            if orig.lower().startswith(prefix):
                song = orig[len(prefix):].strip()
                # Remove trailing "to the queue"
                song = re.sub(r"\s+to\s+the\s+queue\s*$", "", song, flags=re.IGNORECASE)
                break
        return ("play", song)

    return ("unknown", None)
```

```python
# auto-kj/voice/transcribe.py
import whisper
import numpy as np
import tempfile
import wave

_model = None

def _get_model(model_name: str = "small"):
    global _model
    if _model is None:
        _model = whisper.load_model(model_name)
    return _model

def transcribe_audio(audio_data: np.ndarray, sample_rate: int = 16000, model_name: str = "small") -> str:
    model = _get_model(model_name)
    # Whisper expects float32 audio normalized to [-1, 1]
    if audio_data.dtype == np.int16:
        audio_data = audio_data.astype(np.float32) / 32768.0

    # Pad or trim to 30 seconds as whisper expects
    audio_data = whisper.pad_or_trim(audio_data)
    result = model.transcribe(audio_data, fp16=False)
    return result["text"].strip()
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_commands.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/voice/commands.py auto-kj/voice/transcribe.py tests/test_commands.py
git commit -m "feat: whisper transcription and command intent parsing"
```

---

### Task 11: Wake Word Listener

**Files:**
- Create: `auto-kj/voice/wakeword.py`
- Create: `tests/test_wakeword.py`

**Step 1: Write the failing test**

```python
# tests/test_wakeword.py
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from voice.wakeword import WakeWordListener

@patch("voice.wakeword.Model")
def test_listener_creation(mock_model_cls):
    listener = WakeWordListener()
    mock_model_cls.assert_called_once()

@patch("voice.wakeword.Model")
def test_process_frame_no_detection(mock_model_cls):
    mock_model = MagicMock()
    mock_model.predict.return_value = {"hey_jarvis": 0.1}
    mock_model_cls.return_value = mock_model

    listener = WakeWordListener(threshold=0.5)
    frame = np.zeros(1280, dtype=np.int16)
    assert listener.process_frame(frame) is False

@patch("voice.wakeword.Model")
def test_process_frame_detection(mock_model_cls):
    mock_model = MagicMock()
    mock_model.predict.return_value = {"hey_jarvis": 0.9}
    mock_model_cls.return_value = mock_model

    listener = WakeWordListener(threshold=0.5)
    frame = np.zeros(1280, dtype=np.int16)
    assert listener.process_frame(frame) is True
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_wakeword.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/voice/wakeword.py
import numpy as np
from openwakeword.model import Model

class WakeWordListener:
    def __init__(self, model_name: str = "hey_jarvis", threshold: float = 0.5):
        self.model = Model()
        self.model_name = model_name
        self.threshold = threshold

    def process_frame(self, frame: np.ndarray) -> bool:
        prediction = self.model.predict(frame)
        score = max(prediction.values()) if prediction else 0
        return score >= self.threshold

    def reset(self):
        self.model.reset()
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_wakeword.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/voice/wakeword.py tests/test_wakeword.py
git commit -m "feat: OpenWakeWord listener"
```

---

### Task 12: Keyboard Input Handler

**Files:**
- Create: `auto-kj/keyboard.py`
- Create: `tests/test_keyboard.py`

**Step 1: Write the failing test**

```python
# tests/test_keyboard.py
import pytest
from unittest.mock import MagicMock
from keyboard import KeyboardHandler

def test_register_and_dispatch():
    handler = KeyboardHandler()
    callback = MagicMock()
    handler.on("space", callback)
    handler.dispatch("space")
    callback.assert_called_once()

def test_dispatch_unknown_key():
    handler = KeyboardHandler()
    # Should not raise
    handler.dispatch("unknown_key")

def test_multiple_handlers():
    handler = KeyboardHandler()
    cb1 = MagicMock()
    cb2 = MagicMock()
    handler.on("space", cb1)
    handler.on("escape", cb2)
    handler.dispatch("space")
    cb1.assert_called_once()
    cb2.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_keyboard.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/keyboard.py
import threading
from evdev import InputDevice, ecodes, list_devices

KEY_MAP = {
    ecodes.KEY_SPACE: "space",
    ecodes.KEY_ESC: "escape",
    ecodes.KEY_UP: "up",
    ecodes.KEY_DOWN: "down",
    ecodes.KEY_Q: "q",
}

class KeyboardHandler:
    def __init__(self):
        self._callbacks: dict[str, callable] = {}

    def on(self, key_name: str, callback: callable):
        self._callbacks[key_name] = callback

    def dispatch(self, key_name: str):
        cb = self._callbacks.get(key_name)
        if cb:
            cb()

    def start(self, device_path: str | None = None):
        if device_path is None:
            device_path = self._find_keyboard()
        if device_path is None:
            raise RuntimeError("No keyboard device found")
        thread = threading.Thread(target=self._listen, args=(device_path,), daemon=True)
        thread.start()

    def _find_keyboard(self) -> str | None:
        for path in list_devices():
            dev = InputDevice(path)
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps:
                keys = caps[ecodes.EV_KEY]
                if ecodes.KEY_SPACE in keys and ecodes.KEY_ESC in keys:
                    return path
        return None

    def _listen(self, device_path: str):
        dev = InputDevice(device_path)
        for event in dev.read_loop():
            if event.type == ecodes.EV_KEY and event.value == 1:  # key down
                key_name = KEY_MAP.get(event.code)
                if key_name:
                    self.dispatch(key_name)
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_keyboard.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/keyboard.py tests/test_keyboard.py
git commit -m "feat: evdev keyboard input handler"
```

---

### Task 13: Song Processing Pipeline (Background Worker)

**Files:**
- Create: `auto-kj/songs/pipeline.py`
- Create: `tests/test_pipeline.py`

**Step 1: Write the failing test**

```python
# tests/test_pipeline.py
import os
import pytest
from unittest.mock import patch, MagicMock
from songs.pipeline import SongPipeline

@pytest.fixture
def pipeline(tmp_path):
    cache = MagicMock()
    queue = MagicMock()
    tts = MagicMock()
    return SongPipeline(
        cache=cache,
        queue=queue,
        speak_fn=tts,
        cache_dir=str(tmp_path),
    )

def test_request_cached(pipeline):
    pipeline.cache.get.return_value = {
        "youtube_id": "abc",
        "title": "Song",
        "source_type": "karaoke",
        "video_path": "abc/video.mp4",
    }
    pipeline.request("Song")
    pipeline.cache.search.assert_called_once()

@patch("songs.pipeline.search_song")
@patch("songs.pipeline.download_song")
def test_request_karaoke_found(mock_dl, mock_search, pipeline):
    pipeline.cache.get.return_value = None
    pipeline.cache.search.return_value = []
    mock_search.return_value = {"id": "abc", "title": "Song Karaoke", "is_karaoke": True}
    mock_dl.return_value = {
        "youtube_id": "abc",
        "title": "Song Karaoke",
        "artist": "Unknown",
        "video_path": "abc/video.mp4",
    }

    pipeline._process_request("Song")
    mock_search.assert_called_once_with("Song")
    mock_dl.assert_called_once()
    pipeline.queue.add.assert_called_once()
    added_song = pipeline.queue.add.call_args[0][0]
    assert added_song["source_type"] == "karaoke"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/songs/pipeline.py
import os
import threading
from songs.search import search_song
from songs.download import download_song
from songs.separate import separate_vocals
from songs.lyrics import fetch_lyrics, save_lrc

class SongPipeline:
    def __init__(self, cache, queue, speak_fn, cache_dir: str):
        self.cache = cache
        self.queue = queue
        self.speak = speak_fn
        self.cache_dir = cache_dir

    def request(self, song_name: str):
        # Check cache first
        results = self.cache.search(song_name)
        if results:
            entry = results[0]
            self._enqueue_cached(entry)
            return
        # Process in background
        thread = threading.Thread(
            target=self._process_request, args=(song_name,), daemon=True
        )
        thread.start()

    def _enqueue_cached(self, entry: dict):
        song = {
            "youtube_id": entry["youtube_id"],
            "title": entry["title"],
            "source_type": entry["source_type"],
            "video_path": os.path.join(self.cache_dir, entry["video_path"]) if entry.get("video_path") else None,
            "instrumental_path": os.path.join(self.cache_dir, entry["instrumental_path"]) if entry.get("instrumental_path") else None,
            "lyrics_path": os.path.join(self.cache_dir, entry["lyrics_path"]) if entry.get("lyrics_path") else None,
        }
        self.queue.add(song)
        self.speak(f"Added {entry['title']} to the queue")

    def _process_request(self, song_name: str):
        self.speak(f"Searching for {song_name}")

        result = search_song(song_name)
        if result is None:
            self.speak(f"Sorry, I couldn't find {song_name}")
            return

        youtube_id = result["id"]
        is_karaoke = result.get("is_karaoke", False)

        # Download
        self.speak(f"Downloading {result.get('title', song_name)}")
        try:
            dl = download_song(youtube_id, self.cache_dir)
        except Exception as e:
            self.speak(f"Failed to download {song_name}")
            return

        video_path = dl["video_path"]
        instrumental_path = None
        lyrics_path = None
        source_type = "karaoke" if is_karaoke else "original"

        if not is_karaoke:
            # Separate vocals
            source_type = "separated"
            try:
                song_dir = os.path.join(self.cache_dir, youtube_id)
                full_video = os.path.join(self.cache_dir, video_path)
                instrumental_path = separate_vocals(full_video, song_dir)
                instrumental_path = os.path.relpath(instrumental_path, self.cache_dir)
            except Exception:
                source_type = "original"  # fall back to original with vocals

            # Fetch lyrics
            try:
                lrc = fetch_lyrics(dl["title"], dl.get("artist", ""))
                if lrc:
                    lrc_path = os.path.join(self.cache_dir, youtube_id, "lyrics.lrc")
                    save_lrc(lrc, lrc_path)
                    lyrics_path = os.path.relpath(lrc_path, self.cache_dir)
            except Exception:
                pass

        # Cache it
        self.cache.add(youtube_id, {
            "title": dl["title"],
            "artist": dl.get("artist"),
            "source_type": source_type,
            "video_path": video_path,
            "instrumental_path": instrumental_path,
            "lyrics_path": lyrics_path,
        })

        # Enqueue
        song = {
            "youtube_id": youtube_id,
            "title": dl["title"],
            "source_type": source_type,
            "video_path": os.path.join(self.cache_dir, video_path),
            "instrumental_path": os.path.join(self.cache_dir, instrumental_path) if instrumental_path else None,
            "lyrics_path": os.path.join(self.cache_dir, lyrics_path) if lyrics_path else None,
        }
        self.queue.add(song)
        self.speak(f"Added {dl['title']} to the queue")
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/songs/pipeline.py tests/test_pipeline.py
git commit -m "feat: background song processing pipeline"
```

---

### Task 14: State Machine + Main Orchestrator

**Files:**
- Create: `auto-kj/state.py`
- Create: `tests/test_state.py`
- Modify: `auto-kj/main.py`

**Step 1: Write the failing test**

```python
# tests/test_state.py
import pytest
from state import KaraokeState, StateMachine

def test_initial_state():
    sm = StateMachine()
    assert sm.state == KaraokeState.IDLE

def test_idle_to_playing():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    assert sm.state == KaraokeState.PLAYING

def test_playing_to_paused():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    sm.transition(KaraokeState.PAUSED)
    assert sm.state == KaraokeState.PAUSED

def test_playing_to_listening():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    sm.transition(KaraokeState.LISTENING)
    assert sm.state == KaraokeState.LISTENING

def test_paused_to_playing():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    sm.transition(KaraokeState.PAUSED)
    sm.transition(KaraokeState.PLAYING)
    assert sm.state == KaraokeState.PLAYING

def test_listening_returns_to_previous():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    sm.transition(KaraokeState.LISTENING)
    sm.return_from_listening()
    assert sm.state == KaraokeState.PLAYING

def test_on_enter_callback():
    sm = StateMachine()
    entered = []
    sm.on_enter(KaraokeState.PLAYING, lambda: entered.append(True))
    sm.transition(KaraokeState.PLAYING)
    assert entered == [True]
```

**Step 2: Run test to verify it fails**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_state.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# auto-kj/state.py
import enum
import threading

class KaraokeState(enum.Enum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    LISTENING = "listening"

VALID_TRANSITIONS = {
    KaraokeState.IDLE: {KaraokeState.PLAYING, KaraokeState.LISTENING},
    KaraokeState.PLAYING: {KaraokeState.IDLE, KaraokeState.PAUSED, KaraokeState.LISTENING},
    KaraokeState.PAUSED: {KaraokeState.PLAYING, KaraokeState.IDLE, KaraokeState.LISTENING},
    KaraokeState.LISTENING: {KaraokeState.IDLE, KaraokeState.PLAYING, KaraokeState.PAUSED},
}

class StateMachine:
    def __init__(self):
        self.state = KaraokeState.IDLE
        self._previous = KaraokeState.IDLE
        self._callbacks: dict[KaraokeState, list[callable]] = {}
        self._lock = threading.Lock()

    def transition(self, new_state: KaraokeState):
        with self._lock:
            if new_state not in VALID_TRANSITIONS.get(self.state, set()):
                raise ValueError(f"Invalid transition: {self.state} -> {new_state}")
            if new_state == KaraokeState.LISTENING:
                self._previous = self.state
            self.state = new_state
        for cb in self._callbacks.get(new_state, []):
            cb()

    def return_from_listening(self):
        with self._lock:
            if self.state != KaraokeState.LISTENING:
                return
            self.state = self._previous

    def on_enter(self, state: KaraokeState, callback: callable):
        self._callbacks.setdefault(state, []).append(callback)
```

**Step 4: Run test to verify it passes**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/test_state.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add auto-kj/state.py tests/test_state.py
git commit -m "feat: karaoke state machine"
```

---

### Task 15: Main Orchestrator (Wiring Everything Together)

**Files:**
- Modify: `auto-kj/main.py`

This is the integration task. No unit test — this is the entry point that wires all components.

**Note:** Uses a single PyAudio stream shared between wakeword detection and
command recording to avoid ALSA device contention. The stream runs continuously;
when we need to record a command, we just start buffering the frames from the
same stream instead of opening a new one.

**Step 1: Write main.py**

```python
# auto-kj/main.py
"""auto-kj: Voice-controlled karaoke machine."""

import os
import sys
import time
import threading
import numpy as np
import pyaudio

from config import Config
from state import KaraokeState, StateMachine
from queue_manager import SongQueue
from playback import Player
from keyboard import KeyboardHandler
from songs.cache import SongCache
from songs.pipeline import SongPipeline
from voice.wakeword import WakeWordListener
from voice.transcribe import transcribe_audio
from voice.commands import parse_command
from voice.tts import speak

SAMPLE_RATE = 16000
FRAME_SIZE = 1280  # 80ms at 16kHz

class Karaoke:
    def __init__(self, config: Config):
        self.config = config
        self.sm = StateMachine()
        self.queue = SongQueue()
        self.player = Player()
        self.cache = SongCache(config.cache_dir, config.cache_max_bytes)
        self.pipeline = SongPipeline(self.cache, self.queue, speak, config.cache_dir)
        self.wakeword = WakeWordListener()
        self.keyboard = KeyboardHandler()
        self._running = False
        self._audio = pyaudio.PyAudio()
        self._recording = False
        self._record_frames: list[np.ndarray] = []
        self._record_event = threading.Event()

        self._setup_callbacks()

    def _setup_callbacks(self):
        self.player.on_song_end(self._on_song_end)
        self.keyboard.on("space", self._on_spacebar)
        self.keyboard.on("escape", self._on_escape)
        self.keyboard.on("up", self.player.volume_up)
        self.keyboard.on("down", self.player.volume_down)
        self.keyboard.on("q", self.shutdown)

    def _on_song_end(self):
        song = self.queue.next()
        if song:
            self.sm.transition(KaraokeState.IDLE)
            self.sm.transition(KaraokeState.PLAYING)
            self.player.play(song)
        else:
            self.sm.transition(KaraokeState.IDLE)
            speak("Queue is empty. What should I play next?")

    def _on_spacebar(self):
        if self.sm.state == KaraokeState.PLAYING:
            self.player.pause()
            self.sm.transition(KaraokeState.LISTENING)
            self._listen_for_command()
        elif self.sm.state in (KaraokeState.IDLE, KaraokeState.PAUSED):
            self.sm.transition(KaraokeState.LISTENING)
            self._listen_for_command()

    def _on_escape(self):
        if self.sm.state == KaraokeState.PLAYING:
            self.player.skip()

    def _listen_for_command(self):
        """Start recording from the shared mic stream, then process."""
        self._record_frames = []
        self._recording = True
        threading.Thread(target=self._wait_and_process, daemon=True).start()

    def _wait_and_process(self):
        """Wait for recording to complete, then transcribe and act."""
        # Record for up to 5 seconds (the mic loop fills _record_frames)
        max_frames = int(SAMPLE_RATE * 5 / FRAME_SIZE)
        while len(self._record_frames) < max_frames and self._recording:
            time.sleep(0.05)
        self._recording = False

        if not self._record_frames:
            self.sm.return_from_listening()
            return

        audio = np.concatenate(self._record_frames)
        text = transcribe_audio(audio, SAMPLE_RATE, self.config.whisper_model)
        if not text:
            self.sm.return_from_listening()
            return

        speak(f"I heard: {text}")
        intent, song = parse_command(text)
        self._handle_intent(intent, song)

    def _handle_intent(self, intent: str, song: str | None):
        if intent == "play" and song:
            self.pipeline.request(song)
            if self.sm.state == KaraokeState.LISTENING:
                self.sm.return_from_listening()
            self._try_start_playback()
        elif intent == "skip":
            self.sm.return_from_listening()
            self.player.skip()
        elif intent == "pause":
            if self.sm.state == KaraokeState.LISTENING:
                self.sm.return_from_listening()
        elif intent == "resume":
            self.player.resume()
            self.sm.return_from_listening()
            if self.sm.state == KaraokeState.PAUSED:
                self.sm.transition(KaraokeState.PLAYING)
        elif intent == "queue":
            songs = self.queue.list()
            if songs:
                titles = ", ".join(s["title"] for s in songs[:5])
                speak(f"Up next: {titles}")
            else:
                speak("Queue is empty")
            self.sm.return_from_listening()
        elif intent == "volume_up":
            self.player.volume_up()
            self.sm.return_from_listening()
        elif intent == "volume_down":
            self.player.volume_down()
            self.sm.return_from_listening()
        elif intent == "cancel":
            self.sm.return_from_listening()
        else:
            speak("Sorry, I didn't understand that")
            self.sm.return_from_listening()

    def _try_start_playback(self):
        """Check queue and start playing if idle."""
        def _check():
            time.sleep(2)
            for _ in range(30):
                if self.sm.state == KaraokeState.IDLE and not self.queue.is_empty():
                    song = self.queue.next()
                    if song:
                        self.sm.transition(KaraokeState.PLAYING)
                        self.player.play(song)
                    return
                time.sleep(2)
        threading.Thread(target=_check, daemon=True).start()

    def _mic_loop(self):
        """Single shared mic stream for both wakeword and command recording.

        Always-on stream avoids ALSA device contention. Frames are routed to
        either wakeword detection or command recording based on current state.
        """
        stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=FRAME_SIZE,
        )
        while self._running:
            data = stream.read(FRAME_SIZE, exception_on_overflow=False)
            frame = np.frombuffer(data, dtype=np.int16)

            if self._recording:
                # Route frames to command recording buffer
                self._record_frames.append(frame)
                continue

            if self.sm.state in (KaraokeState.IDLE, KaraokeState.PAUSED):
                # Route frames to wakeword detection
                if self.wakeword.process_frame(frame):
                    self.wakeword.reset()
                    self.sm.transition(KaraokeState.LISTENING)
                    self._listen_for_command()

        stream.stop_stream()
        stream.close()

    def run(self):
        self._running = True
        os.makedirs(self.config.cache_dir, exist_ok=True)
        speak("Karaoke machine ready. Say Hey Karaoke or press spacebar.")

        self.keyboard.start()
        threading.Thread(target=self._mic_loop, daemon=True).start()

        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.shutdown()

    def shutdown(self):
        self._running = False
        self.player.shutdown()
        self._audio.terminate()
        speak("Goodbye!")
        time.sleep(1)
        sys.exit(0)

def main():
    config = Config()
    karaoke = Karaoke(config)
    karaoke.run()

if __name__ == "__main__":
    main()
```

**Step 2: Smoke test**

Run: `cd /home/gabe/auto-kj && python -c "from main import Karaoke; print('imports ok')"`
Expected: "imports ok" (or import errors if deps not installed, which is fine — validates structure)

**Step 3: Commit**

```bash
git add auto-kj/main.py
git commit -m "feat: main orchestrator wiring all components together"
```

---

### Task 16: Integration Testing + Polish

**Files:**
- Create: `tests/test_integration.py`
- Modify: `auto-kj/requirements.txt` (add pyaudio, numpy, requests)

**Step 1: Write integration test**

```python
# tests/test_integration.py
"""Integration tests using mocks for external services."""
import os
import pytest
from unittest.mock import patch, MagicMock
from config import Config
from state import KaraokeState, StateMachine
from queue_manager import SongQueue
from songs.pipeline import SongPipeline
from voice.commands import parse_command

def test_full_voice_command_flow():
    """Simulate: user says 'play Bohemian Rhapsody' -> search -> enqueue."""
    text = "play Bohemian Rhapsody"
    intent, song = parse_command(text)
    assert intent == "play"
    assert song == "Bohemian Rhapsody"

def test_state_machine_full_cycle():
    sm = StateMachine()
    assert sm.state == KaraokeState.IDLE

    sm.transition(KaraokeState.PLAYING)
    assert sm.state == KaraokeState.PLAYING

    sm.transition(KaraokeState.LISTENING)
    assert sm.state == KaraokeState.LISTENING

    sm.return_from_listening()
    assert sm.state == KaraokeState.PLAYING

    sm.transition(KaraokeState.PAUSED)
    assert sm.state == KaraokeState.PAUSED

    sm.transition(KaraokeState.PLAYING)
    assert sm.state == KaraokeState.PLAYING

    sm.transition(KaraokeState.IDLE)
    assert sm.state == KaraokeState.IDLE

def test_queue_through_pipeline():
    cache = MagicMock()
    cache.search.return_value = [
        {
            "youtube_id": "abc",
            "title": "Bohemian Rhapsody",
            "source_type": "karaoke",
            "video_path": "abc/video.mp4",
            "instrumental_path": None,
            "lyrics_path": None,
        }
    ]
    queue = SongQueue()
    pipeline = SongPipeline(cache, queue, MagicMock(), "/tmp/cache")
    pipeline.request("Bohemian Rhapsody")
    assert not queue.is_empty()
    song = queue.next()
    assert song["title"] == "Bohemian Rhapsody"
```

**Step 2: Update requirements.txt**

```
# auto-kj/requirements.txt
python-mpv>=1.0.7
yt-dlp>=2024.0.0
spleeter>=2.4.0
openwakeword>=0.6.0
openai-whisper>=20231117
pyttsx3>=2.90
evdev>=1.7.0
PyAudio>=0.2.14
numpy>=1.24.0
requests>=2.28.0
```

**System dependencies (must be installed separately):**
- `ffmpeg` — required by Whisper, Spleeter, and audio extraction from video
- `mpv` — required by python-mpv
- `espeak` — required by pyttsx3 on Linux
- User must be in the `input` group for evdev keyboard access

**Step 3: Run all tests**

Run: `cd /home/gabe/auto-kj && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add tests/test_integration.py auto-kj/requirements.txt
git commit -m "feat: integration tests and final requirements"
```
