import os
import pytest
import threading
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


@patch("playback.Player._is_overnight", return_value=False)
@patch("playback.os.path.exists", return_value=True)
@patch("playback.subprocess.Popen")
def test_wake_screen_replaces_black_mpv_with_idle_image(mock_popen, mock_exists, mock_overnight):
    """After _blank_screen leaves a live black mpv as _idle_proc, wake_screen
    must terminate it and spawn a new mpv showing the idle hero image."""
    procs = []

    def make_proc(*_a, **_kw):
        p = MagicMock()
        p.poll.return_value = None
        procs.append(p)
        return p
    mock_popen.side_effect = make_proc

    player = Player()
    player._blank_screen()
    assert player._screen_blanked is True
    assert len(procs) == 1
    black_proc = procs[0]

    player.wake_screen()

    assert player._screen_blanked is False
    black_proc.terminate.assert_called()
    assert len(procs) == 2, "wake_screen should have spawned a new mpv"
    new_args = mock_popen.call_args_list[-1][0][0]
    assert _IDLE_IMAGE in new_args
    assert "lavfi://[color=black:s=1920x1080:r=1]" not in new_args


@patch("playback.Player._is_overnight", return_value=False)
@patch("playback.os.path.exists", return_value=True)
@patch("playback.subprocess.Popen")
def test_show_idle_once_replaces_black_mpv(mock_popen, mock_exists, mock_overnight):
    """If _show_idle_once is called while the black mpv is the active idle
    proc, it should replace it with the idle image (not no-op)."""
    procs = []

    def make_proc(*_a, **_kw):
        p = MagicMock()
        p.poll.return_value = None
        procs.append(p)
        return p
    mock_popen.side_effect = make_proc

    player = Player()
    player._blank_screen()
    player._screen_blanked = False  # caller has already cleared the flag
    player._show_idle_once()

    assert len(procs) == 2
    new_args = mock_popen.call_args_list[-1][0][0]
    assert _IDLE_IMAGE in new_args


@patch("playback.Player._is_overnight", return_value=False)
@patch("playback.os.path.exists", return_value=True)
@patch("playback.subprocess.Popen")
def test_show_idle_once_is_idempotent_when_already_showing(mock_popen, mock_exists, mock_overnight):
    """When the idle image is already showing, repeated _show_idle_once
    calls must not thrash (no new Popen, no terminate)."""
    procs = []

    def make_proc(*_a, **_kw):
        p = MagicMock()
        p.poll.return_value = None
        procs.append(p)
        return p
    mock_popen.side_effect = make_proc

    player = Player()
    player._show_idle_once()
    assert len(procs) == 1
    first = procs[0]

    player._show_idle_once()
    assert len(procs) == 1, "should not spawn a second mpv"
    first.terminate.assert_not_called()


@patch("playback.Player._is_overnight", return_value=False)
@patch("playback.os.path.exists", return_value=True)
@patch("playback.subprocess.Popen")
def test_idle_subtitle_does_not_leak_temp_files(mock_popen, mock_exists, mock_overnight):
    """Repeated idle/blank cycles must not leak per-cycle .ass temp files."""
    procs = []

    def make_proc(*_a, **_kw):
        p = MagicMock()
        p.poll.return_value = None
        procs.append(p)
        return p
    mock_popen.side_effect = make_proc

    player = Player()
    paths = set()
    # Simulate the hourly idle/blank cycle: image -> blank -> image -> blank ...
    for _ in range(5):
        player._show_idle_once()
        args = mock_popen.call_args[0][0]
        sub_arg = next((a for a in args if isinstance(a, str) and a.startswith("--sub-file=")), None)
        if sub_arg:
            paths.add(sub_arg.split("=", 1)[1])
        player._blank_screen()

    # Expect 5 distinct subtitle files were generated, only at most one should
    # still exist on disk (the most recently written one).
    # Use os.path.isfile (not exists) because os.path.exists is patched.
    assert len(paths) >= 2, "Test setup failed to produce multiple subtitle files"
    surviving = [p for p in paths if os.path.isfile(p)]
    assert len(surviving) <= 1, (
        f"Idle subtitle temp files leak: {len(surviving)} survived: {surviving}"
    )

    for p in surviving:
        try:
            os.unlink(p)
        except OSError:
            pass


@patch("playback.subprocess.Popen")
def test_replacement_does_not_fire_on_end_callback(mock_popen):
    """When _start_mpv replaces a running song, the old proc's _wait_for_end
    thread must not fire on_end_callback (which would skip a queued song)."""
    procs = []

    def make_proc(*_a, **_kw):
        wait_event = threading.Event()
        p = MagicMock()
        p.poll.return_value = None
        p.returncode = 0
        p.stdout = None
        p.wait.side_effect = lambda timeout=None: wait_event.wait(timeout=timeout)
        p.terminate.side_effect = lambda: wait_event.set()
        procs.append(p)
        return p
    mock_popen.side_effect = make_proc

    callback = MagicMock()
    player = Player()
    player.on_song_end(callback)

    # Start first song; thread1 begins waiting on proc1.wait()
    player.play({"source_type": "karaoke", "video_path": "/a.mp4"})
    time.sleep(0.05)

    # Replace with second song - this terminates proc1 and starts proc2
    player.play({"source_type": "karaoke", "video_path": "/b.mp4"})
    # Allow thread1 to drain
    time.sleep(0.1)

    # The first proc was terminated as a replacement, not natural song end.
    # The on_end callback must not have fired (otherwise the queue would skip).
    callback.assert_not_called()


@patch("playback.subprocess.Popen")
def test_natural_song_end_still_fires_callback(mock_popen):
    """When a song ends naturally (not replaced), on_end_callback must still fire."""
    wait_event = threading.Event()
    proc = MagicMock()
    proc.poll.return_value = None
    proc.returncode = 0
    proc.stdout = None
    proc.wait.side_effect = lambda timeout=None: wait_event.wait(timeout=timeout)
    proc.terminate.side_effect = lambda: wait_event.set()
    mock_popen.return_value = proc

    callback = MagicMock()
    player = Player()
    player.on_song_end(callback)

    player.play({"source_type": "karaoke", "video_path": "/a.mp4"})
    time.sleep(0.05)

    # Song ends naturally (proc exits)
    wait_event.set()
    time.sleep(0.1)

    callback.assert_called_once()


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
