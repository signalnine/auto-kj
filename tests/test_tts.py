import pytest
from unittest.mock import patch, MagicMock
from voice.tts import speak


@patch("voice.tts.pyttsx3")
def test_speak(mock_pyttsx3):
    mock_engine = MagicMock()
    mock_pyttsx3.init.return_value = mock_engine
    speak("Hello world")
    # Give the thread a moment to start
    import time
    time.sleep(0.1)
    mock_engine.say.assert_called_once_with("Hello world")
    mock_engine.runAndWait.assert_called_once()
