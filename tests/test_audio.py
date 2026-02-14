"""Tests for JACK audio engine."""
import numpy as np
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from config import Config
from audio import JackAudioEngine, JACK_RATE, OUTPUT_RATE, FRAME_SIZE


class TestJackAudioEngine:
    def _make_config(self, **overrides):
        defaults = dict(
            jack_device="hw:0",
            jack_mic_device="hw:2",
            jack_period=256,
        )
        defaults.update(overrides)
        config = MagicMock()
        for k, v in defaults.items():
            setattr(config, k, v)
        return config

    @patch("audio.subprocess.Popen")
    def test_start_jackd(self, mock_popen):
        config = self._make_config()
        engine = JackAudioEngine(config)
        engine._start_jackd()
        args = mock_popen.call_args[0][0]
        assert args[0] == "jackd"
        assert "-d" in args
        assert "hw:0" in args

    @patch("audio.subprocess.Popen")
    def test_start_zita(self, mock_popen):
        config = self._make_config()
        engine = JackAudioEngine(config)
        engine._start_zita()
        args = mock_popen.call_args[0][0]
        assert args[0] == "zita-a2j"
        assert "hw:2" in args

    def test_get_frame_returns_none_when_stopped(self):
        config = self._make_config()
        engine = JackAudioEngine(config)
        engine._running = False
        result = engine.get_frame()
        assert result is None

    def test_get_frame_returns_correct_size(self):
        config = self._make_config()
        engine = JackAudioEngine(config)
        engine._running = True
        # Pre-fill the frame buffer with enough samples
        samples = np.zeros(FRAME_SIZE + 100, dtype=np.int16)
        engine._frame_buf.append(samples)
        engine._frame_event.set()
        frame = engine.get_frame()
        assert frame is not None
        assert len(frame) == FRAME_SIZE
        assert frame.dtype == np.int16

    def test_process_callback_downsamples(self):
        config = self._make_config()
        engine = JackAudioEngine(config)
        engine._running = True

        # Simulate JACK port with numpy array
        mic_array = np.ones(256, dtype=np.float32) * 0.5

        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array

        engine._process_callback(256)

        # Should have downsampled data in the frame buffer
        assert len(engine._frame_buf) > 0
        total = sum(len(f) for f in engine._frame_buf)
        # 256 samples at 48k -> ~85 samples at 16k
        assert total == 256 // 3

    def test_shutdown_kills_processes(self):
        config = self._make_config()
        engine = JackAudioEngine(config)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        engine._jack_proc = mock_proc
        engine._zita_proc = mock_proc
        engine._running = True

        engine.shutdown()

        assert not engine._running
        assert engine._jack_proc is None
        assert engine._zita_proc is None
        mock_proc.terminate.assert_called()
