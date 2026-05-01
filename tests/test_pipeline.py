import os
import threading
import time
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
    pipeline.cache.search.return_value = [
        {
            "youtube_id": "abc",
            "title": "Song",
            "source_type": "karaoke",
            "video_path": "abc/video.mp4",
            "instrumental_path": None,
            "lyrics_path": None,
        }
    ]
    pipeline.request("Song")
    pipeline.cache.search.assert_called_once()


def test_request_dedups_concurrent_same_song(pipeline):
    """Two back-to-back requests for the same uncached song must result in
    a single _process_request invocation."""
    pipeline.cache.search.return_value = []

    started = threading.Event()
    release = threading.Event()
    call_count = [0]

    def slow_process(name):
        call_count[0] += 1
        started.set()
        release.wait(timeout=2.0)

    with patch.object(pipeline, "_process_request", side_effect=slow_process):
        pipeline.request("Song X")
        assert started.wait(timeout=1.0)
        # Duplicate before first completes
        pipeline.request("Song X")
        # And another with mixed casing/whitespace - should also dedup
        pipeline.request("  song x  ")
        release.set()
        time.sleep(0.15)

    assert call_count[0] == 1


def test_request_dedups_uses_normalized_name(pipeline):
    """Once an in-flight request completes, a fresh request for it should run."""
    pipeline.cache.search.return_value = []

    call_count = [0]
    done = threading.Event()

    def quick_process(name):
        call_count[0] += 1
        done.set()

    with patch.object(pipeline, "_process_request", side_effect=quick_process):
        pipeline.request("Song Y")
        assert done.wait(timeout=1.0)
        time.sleep(0.05)
        done.clear()
        pipeline.request("Song Y")  # in-flight set should be clear by now
        assert done.wait(timeout=1.0)
        time.sleep(0.05)

    assert call_count[0] == 2


@patch("songs.pipeline.search_song")
@patch("songs.pipeline.download_song")
def test_request_karaoke_found(mock_dl, mock_search, pipeline):
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
