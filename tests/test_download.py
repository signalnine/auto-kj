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
