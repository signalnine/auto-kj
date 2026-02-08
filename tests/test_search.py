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
    assert score >= 3


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
    mock_ydl.extract_info.side_effect = [
        {"entries": [{"id": "v1", "title": "Song Cover Guitar", "duration": 200}]},
        {"entries": [{"id": "v2", "title": "Song by Artist", "duration": 200}]},
    ]
    result = search_song("Song")
    assert result is not None
    assert result["id"] == "v2"
    assert result["is_karaoke"] is False
