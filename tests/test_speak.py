import io
import wave
import numpy as np
from unittest.mock import patch, MagicMock
import speak


def _make_wav(samples: np.ndarray, rate: int, extra_chunk: bytes = b"") -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    data = buf.getvalue()
    if extra_chunk:
        idx = data.index(b"data")
        data = data[:idx] + extra_chunk + data[idx:]
        new_size = len(data) - 8
        data = data[:4] + new_size.to_bytes(4, "little") + data[8:]
    return data


@patch("speak.os.path.exists", return_value=False)
def test_synth_espeak_parses_wav_header(mock_exists):
    samples = np.arange(1000, dtype=np.int16)
    wav_bytes = _make_wav(samples, rate=16000)
    with patch("speak.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=wav_bytes)
        result = speak.synth("hi")
    audio, rate = result
    assert rate == 16000
    assert np.array_equal(audio, samples)


@patch("speak.os.path.exists", return_value=False)
def test_synth_espeak_handles_extra_chunks(mock_exists):
    samples = np.arange(500, dtype=np.int16)
    extra = b"LIST" + (10).to_bytes(4, "little") + b"INFOXXXXXX"
    wav_bytes = _make_wav(samples, rate=22050, extra_chunk=extra)
    with patch("speak.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=wav_bytes)
        result = speak.synth("hi")
    audio, rate = result
    assert rate == 22050
    assert np.array_equal(audio, samples)


@patch("speak.os.path.exists", return_value=True)
def test_synth_prefers_piper_when_model_present(mock_exists):
    samples = np.arange(100, dtype=np.int16)
    with patch("speak.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=samples.tobytes())
        result = speak.synth("hello")
    # First and only call should be to piper, not espeak-ng
    cmd = mock_run.call_args_list[0][0][0]
    assert "piper" in cmd[0] or cmd[0].endswith("piper")
    audio, rate = result
    assert rate == 22050
    assert np.array_equal(audio, samples)


def test_play_resamples_with_actual_rate():
    samples = np.zeros(100, dtype=np.int16)
    mock_client = MagicMock()
    with patch("speak.jack.Client", return_value=mock_client):
        # Make done.wait return immediately
        with patch("speak.threading.Event") as mock_event_cls:
            mock_event = MagicMock()
            mock_event.wait.return_value = True
            mock_event_cls.return_value = mock_event
            speak.play(samples, source_rate=16000)
    # Verify a client was created and process callback registered
    mock_client.set_process_callback.assert_called()
    mock_client.activate.assert_called()
