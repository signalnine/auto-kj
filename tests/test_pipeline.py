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
