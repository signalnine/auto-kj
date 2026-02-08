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

    assert cache.get("vid1") is None
    assert cache.get("vid2") is not None
