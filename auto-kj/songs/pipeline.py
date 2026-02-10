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
            self._enqueue_cached(entry, song_name)
            return
        # Process in background
        thread = threading.Thread(
            target=self._process_request, args=(song_name,), daemon=True
        )
        thread.start()

    def _enqueue_cached(self, entry: dict, song_name: str):
        song = {
            "youtube_id": entry["youtube_id"],
            "title": entry["title"],
            "source_type": entry["source_type"],
            "video_path": os.path.join(self.cache_dir, entry["video_path"]) if entry.get("video_path") else None,
            "instrumental_path": os.path.join(self.cache_dir, entry["instrumental_path"]) if entry.get("instrumental_path") else None,
            "lyrics_path": os.path.join(self.cache_dir, entry["lyrics_path"]) if entry.get("lyrics_path") else None,
        }
        self.queue.add(song)
        self.speak(f"Playing {song_name}")

    def _process_request(self, song_name: str):
        result = search_song(song_name)
        if result is None:
            self.speak(f"Sorry, I couldn't find {song_name}")
            return

        youtube_id = result["id"]
        is_karaoke = result.get("is_karaoke", False)

        # Download — announce and wait for TTS to finish before starting
        from voice.tts import wait_for_speech
        self.speak(f"Downloading {result.get('title', song_name)}")
        wait_for_speech()
        try:
            dl = download_song(youtube_id, self.cache_dir)
        except Exception:
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
        self.speak(f"Playing {song_name}")
