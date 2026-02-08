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
