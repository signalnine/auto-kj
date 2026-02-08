import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from voice.wakeword import WakeWordListener


@patch("voice.wakeword.Model")
def test_listener_creation(mock_model_cls):
    listener = WakeWordListener()
    mock_model_cls.assert_called_once()


@patch("voice.wakeword.Model")
def test_process_frame_no_detection(mock_model_cls):
    mock_model = MagicMock()
    mock_model.predict.return_value = {"hey_jarvis": 0.1}
    mock_model_cls.return_value = mock_model

    listener = WakeWordListener(threshold=0.5)
    frame = np.zeros(1280, dtype=np.int16)
    assert listener.process_frame(frame) is False


@patch("voice.wakeword.Model")
def test_process_frame_detection(mock_model_cls):
    mock_model = MagicMock()
    mock_model.predict.return_value = {"hey_jarvis": 0.9}
    mock_model_cls.return_value = mock_model

    listener = WakeWordListener(threshold=0.5)
    frame = np.zeros(1280, dtype=np.int16)
    assert listener.process_frame(frame) is True
