# OLED Screen Protection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use conclave:executing-plans to implement this plan task-by-task.

**Goal:** Prevent OLED burn-in by blanking the idle screen after 10 minutes, waking it on mic noise, and playing a pixel-refresh video overnight (2am-6am).

**Architecture:** Three features layered onto Player's existing idle image system. A `_screen_blanked` flag tracks whether the idle image has been turned off. The mic loop in main.py monitors peak levels and calls `player.wake_screen()` when noise is detected. A background thread in Player checks the clock and switches between idle image mode and pixel-refresh video mode during overnight hours. The pixel-refresh video is downloaded once via yt-dlp and cached.

**Tech Stack:** Python threading, yt-dlp (already installed), mpv (already used), datetime

---

### Task 1: Screen blank after 10 minutes

**Files:**
- Modify: `auto-kj/playback.py` (Player class)
- Test: `tests/test_playback.py`

**Dependencies:** none

**Step 1: Write failing tests**

Add to `tests/test_playback.py`:

```python
from unittest.mock import patch, MagicMock, call
import time


@patch("playback.subprocess.Popen")
def test_screen_blanks_after_timeout(mock_popen):
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


def test_screen_blanked_flag_set_after_blank():
    """_screen_blanked is True after screen blanks."""
    player = Player()
    player._screen_blanked = False
    player._blank_screen()
    assert player._screen_blanked is True


@patch("playback.subprocess.Popen")
def test_wake_screen_shows_idle_when_blanked(mock_popen):
    """wake_screen re-shows idle image when screen is blanked."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # first call for idle
    mock_popen.return_value = mock_proc
    player = Player()
    player._screen_blanked = True
    player.wake_screen()
    assert player._screen_blanked is False
    # Should have spawned mpv
    assert mock_popen.called


def test_wake_screen_noop_when_not_blanked():
    """wake_screen does nothing if screen is already on."""
    player = Player()
    player._screen_blanked = False
    player.wake_screen()  # should not raise
    assert player._screen_blanked is False
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_playback.py -v`
Expected: FAIL — `_screen_blank_seconds`, `_blank_screen`, `wake_screen` don't exist

**Step 3: Implement screen blanking in Player**

In `auto-kj/playback.py`, modify `__init__`:
```python
def __init__(self):
    self._proc: subprocess.Popen | None = None
    self._idle_proc: subprocess.Popen | None = None
    self._idle_cycle_stop: threading.Event | None = None
    self._on_end_callback = None
    self._volume = 100
    self._paused = False
    self._lock = threading.Lock()
    self._screen_blanked = False
    self._screen_blank_seconds = 600  # 10 minutes
```

Add `_blank_screen()` method:
```python
def _blank_screen(self):
    """Blank the screen to prevent OLED burn-in."""
    self._kill_idle_proc()
    self._screen_blanked = True
    print("[player] screen blanked (OLED protection)")
```

Add `wake_screen()` method:
```python
def wake_screen(self):
    """Wake the screen from blank state by re-showing idle image."""
    if not self._screen_blanked:
        return
    self._screen_blanked = False
    self._show_idle_once()
```

Modify the `_cycle` closure in `show_idle_image()` to blank after timeout, then cycle hourly:
```python
def show_idle_image(self):
    """Display the idle hero image on screen with a song suggestion.

    Blanks after _screen_blank_seconds to prevent OLED burn-in.
    Cycles to a new suggestion every hour.
    """
    self._stop_idle_cycle()
    self._screen_blanked = False
    self._show_idle_once()
    stop = threading.Event()
    self._idle_cycle_stop = stop
    blank_seconds = self._screen_blank_seconds
    def _cycle():
        # First wait: blank after timeout
        if not stop.wait(blank_seconds):
            self._blank_screen()
        # Then cycle hourly: show for blank_seconds, then blank again
        while not stop.wait(3600 - blank_seconds):
            self._show_idle_once()
            self._screen_blanked = False
            if not stop.wait(blank_seconds):
                self._blank_screen()
    threading.Thread(target=_cycle, daemon=True).start()
```

Also update `hide_idle_image()` to reset the flag:
```python
def hide_idle_image(self):
    """Stop displaying the idle hero image."""
    self._stop_idle_cycle()
    self._kill_idle_proc()
    self._screen_blanked = False
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_playback.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All 87+ tests pass

**Step 6: Commit**

```bash
git add auto-kj/playback.py tests/test_playback.py
git commit -m "feat: blank idle screen after 10 min for OLED protection"
```

---

### Task 2: Wake screen on mic noise

**Files:**
- Modify: `auto-kj/main.py` (Karaoke._mic_loop)
- Test: `tests/test_integration.py` (or inline in test_playback.py)

**Dependencies:** Task 1

**Step 1: Write failing test**

Add to `tests/test_playback.py`:

```python
@patch("playback.subprocess.Popen")
def test_wake_screen_resets_blank_timer(mock_popen):
    """Waking the screen restarts the blank timer cycle."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player._screen_blanked = True
    player.wake_screen()
    assert player._screen_blanked is False
    # The idle cycle should be running (new suggestion shown)
    assert player._idle_proc is not None or mock_popen.called
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_playback.py::test_wake_screen_resets_blank_timer -v`
Expected: May pass already from Task 1 implementation. If so, proceed.

**Step 3: Add noise detection to mic loop**

In `auto-kj/main.py`, modify `_mic_loop()`. Add a noise threshold and cooldown. After the existing `self._clip_buffer.append(frame)` line and before the recording check, add wake-on-noise logic:

```python
def _mic_loop(self):
    print("Mic stream opened — listening for wakeword...")
    frame_count = 0
    wake_threshold = 500  # well above noise floor of 8-12
    last_wake = 0
    wake_cooldown = 30  # seconds between wake attempts
    while self._running:
        frame = self._audio.get_frame()
        if frame is None:
            break

        self._clip_buffer.append(frame)

        # Wake screen on mic noise (OLED burn-in protection)
        peak = int(np.max(np.abs(frame)))
        if peak > wake_threshold and self.player._screen_blanked:
            now = time.monotonic()
            if now - last_wake > wake_cooldown:
                last_wake = now
                self.player.wake_screen()
                print(f"[screen] woke on mic noise (peak={peak})")

        if self._recording:
            self._record_frames.append(frame)
            continue

        if self.sm.state in (KaraokeState.IDLE, KaraokeState.PAUSED):
            if self.wakeword.process_frame(frame):
                print("Wakeword detected!")
                self.wakeword.reset()
                post_frames = []
                for _ in range(6):
                    pf = self._audio.get_frame()
                    if pf is None:
                        break
                    self._clip_buffer.append(pf)
                    post_frames.append(pf)
                threading.Thread(
                    target=self._save_clip,
                    args=("detected", post_frames),
                    daemon=True,
                ).start()
                self.sm.transition(KaraokeState.LISTENING)
                self._listen_for_command()
            frame_count += 1
            if frame_count % 500 == 0:
                print(f"[mic] frames={frame_count}, peak={peak}")
```

Note: the `peak` variable is now computed once earlier and reused in the existing frame_count logging, avoiding computing it twice.

**Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests pass (mic loop is not unit tested directly, the integration test covers it)

**Step 5: Commit**

```bash
git add auto-kj/main.py tests/test_playback.py
git commit -m "feat: wake screen on mic noise detection"
```

---

### Task 3: Overnight pixel-refresh video (2am-6am)

**Files:**
- Modify: `auto-kj/playback.py` (Player class)
- Test: `tests/test_playback.py`

**Dependencies:** Task 1

**Step 1: Write failing tests**

Add to `tests/test_playback.py`:

```python
from unittest.mock import patch, MagicMock
from datetime import datetime


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


@patch("playback.subprocess.Popen")
@patch("playback.Player._get_refresh_video_path")
@patch("playback.Player._is_overnight")
def test_show_idle_shows_image_during_day(mock_overnight, mock_path, mock_popen):
    mock_overnight.return_value = False
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    player = Player()
    player._show_idle_once()
    args = mock_popen.call_args[0][0]
    assert _IDLE_IMAGE in args
    assert "--loop" not in args
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_playback.py -v`
Expected: FAIL — `_is_overnight`, `_get_refresh_video_path` don't exist

**Step 3: Implement overnight pixel-refresh**

In `auto-kj/playback.py`, add `datetime` import at top:
```python
from datetime import datetime
```

Add a constant for the refresh video cache path:
```python
_REFRESH_VIDEO_CACHE = os.path.expanduser("~/.auto-kj/cache/pixel-refresh.mp4")
```

Add these methods to Player:

```python
def _is_overnight(self) -> bool:
    """Check if current time is in the overnight refresh window (2am-6am)."""
    hour = datetime.now().hour
    return 2 <= hour < 6

def _get_refresh_video_path(self) -> str | None:
    """Get path to cached pixel-refresh video, downloading if needed."""
    if os.path.exists(_REFRESH_VIDEO_CACHE):
        return _REFRESH_VIDEO_CACHE
    try:
        os.makedirs(os.path.dirname(_REFRESH_VIDEO_CACHE), exist_ok=True)
        subprocess.run(
            [
                "yt-dlp",
                "-f", "bestvideo[height<=1080][ext=mp4]",
                "--no-audio",
                "-o", _REFRESH_VIDEO_CACHE,
                "https://www.youtube.com/watch?v=mMDGLOOPOIs",
            ],
            capture_output=True, timeout=120,
        )
        if os.path.exists(_REFRESH_VIDEO_CACHE):
            print(f"[player] downloaded pixel-refresh video")
            return _REFRESH_VIDEO_CACHE
    except Exception as e:
        print(f"[player] failed to download pixel-refresh video: {e}")
    return None
```

Modify `_show_idle_once()` to check for overnight mode:

```python
def _show_idle_once(self):
    with self._lock:
        if self._idle_proc and self._idle_proc.poll() is None:
            return
        if self._is_overnight():
            path = self._get_refresh_video_path()
            if path:
                self._idle_proc = subprocess.Popen(
                    [
                        "mpv",
                        "--vo=drm", "--drm-connector=auto",
                        "--no-audio",
                        "--really-quiet",
                        "--loop",
                        path,
                    ],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                print("[player] playing overnight pixel-refresh video")
                return
        if not os.path.exists(_IDLE_IMAGE):
            print(f"[player] idle image not found: {_IDLE_IMAGE}")
            return
        song = random.choice(_SONG_SUGGESTIONS)
        sub_path = self._write_idle_subtitle(song)
        self._idle_proc = subprocess.Popen(
            [
                "mpv",
                "--vo=drm", "--drm-connector=auto",
                "--image-display-duration=inf",
                "--no-audio",
                "--really-quiet",
                f"--sub-file={sub_path}",
                _IDLE_IMAGE,
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"[player] showing idle image (try: {song})")
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_playback.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add auto-kj/playback.py tests/test_playback.py
git commit -m "feat: overnight pixel-refresh video for OLED protection (2am-6am)"
```

---

### Task 4: Final integration and deploy

**Files:**
- None (verification only)

**Dependencies:** Tasks 1, 2, 3

**Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests pass

**Step 2: Deploy to post**

```bash
rsync -av auto-kj/ post:auto-kj/auto-kj/
ssh post 'sudo systemctl restart auto-kj'
```

**Step 3: Verify service started**

```bash
sleep 10 && ssh post 'journalctl -u auto-kj --no-pager -n 10'
```

Expected: Service running, idle image showing, mic stream open.

**Step 4: Commit any remaining changes**

```bash
git add -A
git commit -m "feat: OLED screen protection - blank, wake-on-noise, overnight refresh"
git push
```
