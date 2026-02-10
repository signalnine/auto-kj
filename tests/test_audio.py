"""Tests for JACK audio engine."""
import numpy as np
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from config import Config
from audio import SchroederReverb, JackAudioEngine, JACK_RATE, OUTPUT_RATE, FRAME_SIZE


class TestSchroederReverb:
    def test_passthrough_when_wet_zero(self):
        reverb = SchroederReverb(JACK_RATE, wet=0.0)
        block = np.random.randn(256).astype(np.float32)
        out = reverb.process(block)
        np.testing.assert_array_equal(out, block)

    def test_output_shape_matches_input(self):
        reverb = SchroederReverb(JACK_RATE, wet=0.3)
        block = np.random.randn(256).astype(np.float32)
        out = reverb.process(block)
        assert out.shape == block.shape
        assert out.dtype == np.float32

    def test_wet_mix_changes_output(self):
        reverb = SchroederReverb(JACK_RATE, wet=0.5)
        block = np.zeros(256, dtype=np.float32)
        block[0] = 1.0  # impulse
        out = reverb.process(block)
        # With wet > 0, the reverb tail should make the output differ from input
        assert not np.array_equal(out, block)

    def test_multiple_blocks_accumulate_reverb(self):
        reverb = SchroederReverb(JACK_RATE, wet=0.4)
        # First block with impulse
        block1 = np.zeros(256, dtype=np.float32)
        block1[0] = 1.0
        reverb.process(block1)
        # Process enough silent blocks for comb delays (~1600 samples) to produce output
        found_tail = False
        for _ in range(10):
            block = np.zeros(256, dtype=np.float32)
            out = reverb.process(block)
            if np.max(np.abs(out)) > 0:
                found_tail = True
                break
        assert found_tail, "Reverb tail should appear after enough blocks"


class TestJackAudioEngine:
    def _make_config(self, **overrides):
        defaults = dict(
            jack_device="hw:0",
            jack_mic_device="hw:2",
            jack_period=256,
            mic_gain=1.5,
            reverb_wet=0.3,
            monitor_enabled=True,
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

    def test_mute_unmute_monitor(self):
        config = self._make_config()
        engine = JackAudioEngine(config)
        assert not engine._monitor_muted
        engine.mute_monitor()
        assert engine._monitor_muted
        engine.unmute_monitor()
        assert not engine._monitor_muted

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
        config = self._make_config(monitor_enabled=False)
        engine = JackAudioEngine(config)
        engine._running = True

        # Simulate JACK ports with numpy arrays
        mic_array = np.ones(256, dtype=np.float32) * 0.5
        monitor_L_array = np.zeros(256, dtype=np.float32)
        monitor_R_array = np.zeros(256, dtype=np.float32)

        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array
        engine._monitor_L = MagicMock()
        engine._monitor_L.get_array.return_value = monitor_L_array
        engine._monitor_R = MagicMock()
        engine._monitor_R.get_array.return_value = monitor_R_array

        engine._process_callback(256)

        # Should have downsampled data in the frame buffer
        assert len(engine._frame_buf) > 0
        total = sum(len(f) for f in engine._frame_buf)
        # 256 samples at 48k -> ~85 samples at 16k
        assert total == 256 // 3

    def test_process_callback_applies_reverb_when_monitoring(self):
        config = self._make_config(monitor_enabled=True, mic_gain=2.0)
        engine = JackAudioEngine(config)
        engine._running = True

        mic_array = np.ones(256, dtype=np.float32) * 0.1
        monitor_L_array = np.zeros(256, dtype=np.float32)
        monitor_R_array = np.zeros(256, dtype=np.float32)

        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array
        engine._monitor_L = MagicMock()
        engine._monitor_L.get_array.return_value = monitor_L_array
        engine._monitor_R = MagicMock()
        engine._monitor_R.get_array.return_value = monitor_R_array

        engine._process_callback(256)

        # Monitor should have non-zero output (gain * reverb applied)
        assert np.max(np.abs(monitor_L_array)) > 0

    def test_process_callback_silences_when_muted(self):
        config = self._make_config(monitor_enabled=True)
        engine = JackAudioEngine(config)
        engine._running = True
        engine._monitor_muted = True

        mic_array = np.ones(256, dtype=np.float32) * 0.5
        monitor_L_array = np.zeros(256, dtype=np.float32)
        monitor_R_array = np.zeros(256, dtype=np.float32)

        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array
        engine._monitor_L = MagicMock()
        engine._monitor_L.get_array.return_value = monitor_L_array
        engine._monitor_R = MagicMock()
        engine._monitor_R.get_array.return_value = monitor_R_array

        engine._process_callback(256)

        # Monitor should be silent when muted
        np.testing.assert_array_equal(monitor_L_array, 0)
        np.testing.assert_array_equal(monitor_R_array, 0)

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
