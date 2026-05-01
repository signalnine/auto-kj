import io
import time
import wave
import numpy as np
from unittest.mock import patch, MagicMock
import voice.tts as tts_mod


def _make_wav(samples: np.ndarray, rate: int, extra_chunk: bytes = b"") -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    data = buf.getvalue()
    if extra_chunk:
        # Inject extra chunk between fmt and data chunks
        # Find 'data' chunk and insert before it
        idx = data.index(b"data")
        data = data[:idx] + extra_chunk + data[idx:]
        # Fix RIFF size
        new_size = len(data) - 8
        data = data[:4] + new_size.to_bytes(4, "little") + data[8:]
    return data


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
        stdout=_make_wav(np.zeros(1000, dtype=np.int16), rate=22050),
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
        stdout=_make_wav(np.zeros(1000, dtype=np.int16), rate=22050),
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


def test_synth_espeak_parses_wav_header():
    samples = np.arange(1000, dtype=np.int16)
    wav_bytes = _make_wav(samples, rate=16000)
    with patch("voice.tts.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=wav_bytes)
        result = tts_mod._synth_espeak("hi")
    assert result is not None
    audio, rate = result
    assert rate == 16000
    assert np.array_equal(audio, samples)


def test_synth_espeak_handles_extra_chunks():
    samples = np.arange(500, dtype=np.int16)
    extra = b"LIST" + (10).to_bytes(4, "little") + b"INFOXXXXXX"
    wav_bytes = _make_wav(samples, rate=22050, extra_chunk=extra)
    with patch("voice.tts.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=wav_bytes)
        result = tts_mod._synth_espeak("hi")
    assert result is not None
    audio, rate = result
    assert rate == 22050
    assert np.array_equal(audio, samples)


@patch("voice.tts.os.path.exists", return_value=False)
def test_speak_uses_actual_espeak_rate(mock_exists):
    _reset_tts()
    mock_engine = MagicMock()
    tts_mod.set_audio_engine(mock_engine)
    samples = np.zeros(800, dtype=np.int16)
    wav_bytes = _make_wav(samples, rate=16000)
    with patch("voice.tts.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=wav_bytes)
        tts_mod.speak("Hello world")
        time.sleep(0.3)
    args, _ = mock_engine.play_buffer.call_args
    _audio, rate_arg = args
    assert rate_arg == 16000
    _reset_tts()
