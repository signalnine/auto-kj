import time
import numpy as np
from unittest.mock import patch, MagicMock
import voice.tts as tts_mod


def _reset_tts():
    """Reset module state so the worker starts fresh."""
    tts_mod._started = False
    tts_mod._audio_engine = None


@patch("voice.tts.subprocess.run")
@patch("voice.tts.os.path.exists", return_value=False)
def test_speak_espeak_fallback(mock_exists, mock_run):
    _reset_tts()
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=b'\x00' * 44 + np.zeros(1000, dtype=np.int16).tobytes(),
    )
    tts_mod.speak("Hello world")
    time.sleep(0.3)
    # Should have called espeak-ng and then aplay (as fallback)
    assert mock_run.call_count >= 1


@patch("voice.tts.subprocess.run")
@patch("voice.tts.os.path.exists", return_value=False)
def test_speak_with_jack_engine(mock_exists, mock_run):
    _reset_tts()
    mock_engine = MagicMock()
    tts_mod.set_audio_engine(mock_engine)
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=b'\x00' * 44 + np.zeros(1000, dtype=np.int16).tobytes(),
    )
    tts_mod.speak("Hello world")
    time.sleep(0.3)
    # Should have muted monitor, played through JACK, then unmuted
    mock_engine.mute_monitor.assert_called()
    mock_engine.play_buffer.assert_called()
    mock_engine.unmute_monitor.assert_called()
    _reset_tts()


def test_set_audio_engine():
    _reset_tts()
    mock_engine = MagicMock()
    tts_mod.set_audio_engine(mock_engine)
    assert tts_mod._audio_engine is mock_engine
    _reset_tts()
