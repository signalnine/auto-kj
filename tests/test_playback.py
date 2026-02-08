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
