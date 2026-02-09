import pytest
import time
from unittest.mock import patch, MagicMock
import voice.tts as tts_mod


@patch("voice.tts.pyttsx3")
def test_speak(mock_pyttsx3):
    # Reset module state so the worker starts fresh with our mock
    tts_mod._started = False
    mock_engine = MagicMock()
    mock_pyttsx3.init.return_value = mock_engine
    tts_mod.speak("Hello world")
    # Give the worker thread time to process
    time.sleep(0.2)
    mock_engine.say.assert_called_once_with("Hello world")
    mock_engine.runAndWait.assert_called_once()
