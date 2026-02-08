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
