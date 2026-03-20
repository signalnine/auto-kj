import pytest
import time
from datetime import datetime
from unittest.mock import patch, MagicMock
from playback import Player, _IDLE_IMAGE


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


@patch("playback.os.path.exists", return_value=True)
@patch("playback.subprocess.Popen")
def test_screen_blanks_after_timeout(mock_popen, mock_exists):
    """Idle image process is killed after blank timeout."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player._screen_blank_seconds = 0.1  # short timeout for test
    player.show_idle_image()
    assert player._idle_proc is not None
    time.sleep(0.3)
    mock_proc.terminate.assert_called()


@patch("playback.subprocess.Popen")
def test_screen_blanked_shows_black(mock_popen):
    """_blank_screen spawns mpv with solid black to cover TTY."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player._blank_screen()
    assert player._screen_blanked is True
    args = mock_popen.call_args[0][0]
    assert "lavfi://[color=black:s=1920x1080:r=1]" in args


@patch("playback.os.path.exists", return_value=True)
@patch("playback.subprocess.Popen")
def test_wake_screen_shows_idle_when_blanked(mock_popen, mock_exists):
    """wake_screen re-shows idle image when screen is blanked."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player._screen_blanked = True
    player.wake_screen()
    assert player._screen_blanked is False
    assert mock_popen.called


def test_wake_screen_noop_when_not_blanked():
    """wake_screen does nothing if screen is already on."""
    player = Player()
    player._screen_blanked = False
    player.wake_screen()  # should not raise
    assert player._screen_blanked is False


@patch("playback.os.path.exists", return_value=True)
@patch("playback.subprocess.Popen")
def test_wake_screen_resets_blank_timer(mock_popen, mock_exists):
    """Waking the screen restarts the blank timer cycle."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player._screen_blanked = True
    player.wake_screen()
    assert player._screen_blanked is False
    assert player._idle_proc is not None or mock_popen.called


@patch("playback.datetime")
def test_is_overnight_true_at_3am(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 18, 3, 0)
    player = Player()
    assert player._is_overnight() is True


@patch("playback.datetime")
def test_is_overnight_false_at_noon(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 18, 12, 0)
    player = Player()
    assert player._is_overnight() is False


@patch("playback.datetime")
def test_is_overnight_boundary_2am(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 18, 2, 0)
    player = Player()
    assert player._is_overnight() is True


@patch("playback.datetime")
def test_is_overnight_boundary_6am(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 18, 6, 0)
    player = Player()
    assert player._is_overnight() is False


@patch("playback.subprocess.Popen")
@patch("playback.Player._get_refresh_video_path")
@patch("playback.Player._is_overnight")
def test_show_idle_plays_refresh_video_overnight(mock_overnight, mock_path, mock_popen):
    mock_overnight.return_value = True
    mock_path.return_value = "/cache/pixel-refresh.mp4"
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player._show_idle_once()
    args = mock_popen.call_args[0][0]
    assert "/cache/pixel-refresh.mp4" in args
    assert "--loop" in args


@patch("playback.os.path.exists", return_value=True)
@patch("playback.subprocess.Popen")
@patch("playback.Player._get_refresh_video_path")
@patch("playback.Player._is_overnight")
def test_show_idle_shows_image_during_day(mock_overnight, mock_path, mock_popen, mock_exists):
    mock_overnight.return_value = False
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player._show_idle_once()
    args = mock_popen.call_args[0][0]
    assert _IDLE_IMAGE in args
    assert "--loop" not in args
