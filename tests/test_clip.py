import os
import wave
import collections
import numpy as np
from unittest.mock import MagicMock, patch

from config import Config


def test_save_clip_writes_valid_wav(tmp_path):
    """_save_clip writes a valid 16kHz mono 16-bit WAV from the rolling buffer."""
    config = Config(clips_dir=str(tmp_path))

    # Build a minimal Karaoke-like object with just what _save_clip needs
    from main import Karaoke

    with patch.object(Karaoke, "__init__", lambda self, *a, **kw: None):
        k = Karaoke.__new__(Karaoke)
    k.config = config
    k._clip_buffer = collections.deque(maxlen=25)

    # Fill buffer with 10 frames of 1280 samples each (~0.8s)
    for i in range(10):
        k._clip_buffer.append(np.zeros(1280, dtype=np.int16) + i * 100)

    # Import OUTPUT_RATE from audio module (mocked, so set it directly)
    import main as main_mod
    original_rate = main_mod.OUTPUT_RATE
    main_mod.OUTPUT_RATE = 16000
    try:
        k._save_clip("test")
    finally:
        main_mod.OUTPUT_RATE = original_rate

    # Find the saved file
    files = list(tmp_path.glob("*_test.wav"))
    assert len(files) == 1

    # Validate WAV format
    with wave.open(str(files[0]), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.getnframes() == 12800  # 10 frames * 1280 samples


def test_save_clip_with_extra_frames(tmp_path):
    """_save_clip appends extra_frames after the rolling buffer."""
    config = Config(clips_dir=str(tmp_path))

    from main import Karaoke

    with patch.object(Karaoke, "__init__", lambda self, *a, **kw: None):
        k = Karaoke.__new__(Karaoke)
    k.config = config
    k._clip_buffer = collections.deque(maxlen=25)

    # 5 frames in buffer + 3 extra
    for i in range(5):
        k._clip_buffer.append(np.zeros(1280, dtype=np.int16))
    extra = [np.zeros(1280, dtype=np.int16) for _ in range(3)]

    import main as main_mod
    original_rate = main_mod.OUTPUT_RATE
    main_mod.OUTPUT_RATE = 16000
    try:
        k._save_clip("detected", extra)
    finally:
        main_mod.OUTPUT_RATE = original_rate

    files = list(tmp_path.glob("*_detected.wav"))
    assert len(files) == 1

    with wave.open(str(files[0]), "rb") as wf:
        assert wf.getnframes() == 10240  # 8 frames * 1280


def test_save_clip_empty_buffer(tmp_path):
    """_save_clip does nothing when buffer is empty."""
    config = Config(clips_dir=str(tmp_path))

    from main import Karaoke

    with patch.object(Karaoke, "__init__", lambda self, *a, **kw: None):
        k = Karaoke.__new__(Karaoke)
    k.config = config
    k._clip_buffer = collections.deque(maxlen=25)

    k._save_clip("missed")

    files = list(tmp_path.glob("*.wav"))
    assert len(files) == 0
