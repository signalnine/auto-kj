import pytest
from unittest.mock import patch, MagicMock
from playback import Player


@patch("playback.subprocess.Popen")
def test_play_karaoke_video(mock_popen):
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player.play({
        "source_type": "karaoke",
        "video_path": "/cache/abc123/video.mp4",
    })
    args = mock_popen.call_args[0][0]
    assert "/cache/abc123/video.mp4" in args
    assert "--ao=jack" in args


@patch("playback.subprocess.Popen")
def test_play_separated_uses_instrumental(mock_popen):
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player.play({
        "source_type": "separated",
        "instrumental_path": "/cache/abc123/accompaniment.wav",
        "video_path": "/cache/abc123/video.mp4",
    })
    args = mock_popen.call_args[0][0]
    assert "/cache/abc123/accompaniment.wav" in args


@patch("playback.subprocess.Popen")
def test_mpv_uses_jack_audio(mock_popen):
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player.play({
        "source_type": "karaoke",
        "video_path": "/cache/abc123/video.mp4",
    })
    args = mock_popen.call_args[0][0]
    assert "--ao=jack" in args
    assert "--ao=alsa" not in " ".join(args)


def test_volume_up():
    player = Player()
    player.volume_up()
    assert player._volume == 110


def test_volume_down():
    player = Player()
    player.volume_down()
    assert player._volume == 90


def test_volume_clamp():
    player = Player()
    player._volume = 150
    player.volume_up()
    assert player._volume == 150
    player._volume = 0
    player.volume_down()
    assert player._volume == 0
