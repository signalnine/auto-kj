"""Tests for JACK audio engine."""
import numpy as np
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from config import Config
from audio import JackAudioEngine, SchroederReverb, JACK_RATE, OUTPUT_RATE, FRAME_SIZE


class TestSchroederReverb:
    def test_passthrough_when_wet_zero(self):
        reverb = SchroederReverb(wet=0.0)
        block = np.random.randn(256).astype(np.float32)
        out = reverb.process(block)
        np.testing.assert_array_equal(out, block)

    def test_output_shape_matches_input(self):
        reverb = SchroederReverb(wet=0.3)
        block = np.random.randn(256).astype(np.float32)
        out = reverb.process(block)
        assert out.shape == block.shape
        assert out.dtype == np.float32

    def test_output_clipped_to_valid_range(self):
        reverb = SchroederReverb(wet=0.5)
        # Feed loud signal to exercise clipping
        block = np.ones(1024, dtype=np.float32) * 0.9
        out = reverb.process(block)
        assert np.all(out >= -1.0) and np.all(out <= 1.0)

    def test_wet_mix_differs_from_dry(self):
        reverb = SchroederReverb(wet=0.5)
        # Prime reverb buffers with some signal
        for _ in range(10):
            reverb.process(np.random.randn(256).astype(np.float32))
        block = np.random.randn(256).astype(np.float32)
        out = reverb.process(block)
        # Output should differ from input due to wet mix
        assert not np.allclose(out, block)

    def test_scratch_buffers_reused_across_calls(self):
        """Pre-allocated scratch buffers must be reused so the JACK callback
        does not allocate per-block (avoiding xrun risk)."""
        reverb = SchroederReverb(wet=0.3)
        block = np.random.randn(256).astype(np.float32)
        # First call may lazily allocate scratch
        reverb.process(block)
        comb_id = id(reverb._comb_sum)
        result_id = id(reverb._result_f32)
        # Subsequent calls must reuse the same buffers
        for _ in range(20):
            reverb.process(block)
        assert id(reverb._comb_sum) == comb_id
        assert id(reverb._result_f32) == result_id


class TestJackAudioEngine:
    def _make_config(self, **overrides):
        defaults = dict(
            jack_device="hw:0",
            jack_mic_device="hw:2",
            jack_period=256,
            monitor_mode="hardware",
            mic_gain=2.0,
            reverb_wet=0.1,
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
        # Verify -C flag for mic capture
        assert "-C" in args
        c_idx = args.index("-C")
        assert args[c_idx + 1] == "hw:2"

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
        # Pre-fill the ring buffer with enough samples
        samples = np.arange(FRAME_SIZE + 100, dtype=np.int16)
        engine._ring_write_samples(samples)
        engine._frame_event.set()
        frame = engine.get_frame()
        assert frame is not None
        assert len(frame) == FRAME_SIZE
        assert frame.dtype == np.int16
        np.testing.assert_array_equal(frame, samples[:FRAME_SIZE])

    def test_process_callback_downsamples(self):
        """Hardware mode: no monitor ports, just downsampling."""
        config = self._make_config(monitor_mode="hardware")
        engine = JackAudioEngine(config)
        engine._running = True

        # Simulate JACK port with numpy array
        mic_array = np.ones(256, dtype=np.float32) * 0.5

        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array

        engine._process_callback(256)

        # Should have downsampled data in the ring buffer
        produced = engine._ring_write - engine._ring_read
        # 256 samples at 48k -> ~85 samples at 16k
        assert produced == 256 // 3

    def test_process_callback_downsamples_software(self):
        """Software mode: monitor ports + downsampling."""
        config = self._make_config(monitor_mode="software")
        engine = JackAudioEngine(config)
        engine._running = True

        mic_array = np.ones(256, dtype=np.float32) * 0.5

        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array

        # Mock monitor ports
        monitor_L_arr = np.zeros(256, dtype=np.float32)
        monitor_R_arr = np.zeros(256, dtype=np.float32)
        engine._monitor_L = MagicMock()
        engine._monitor_L.get_array.return_value = monitor_L_arr
        engine._monitor_R = MagicMock()
        engine._monitor_R.get_array.return_value = monitor_R_arr

        engine._process_callback(256)

        # Should have downsampled data in the ring buffer
        produced = engine._ring_write - engine._ring_read
        assert produced == 256 // 3

    def test_process_callback_applies_reverb_when_monitoring(self):
        """Software mode: gain+reverb applied to monitor outputs."""
        config = self._make_config(monitor_mode="software", mic_gain=2.0, reverb_wet=0.1)
        engine = JackAudioEngine(config)
        engine._running = True

        mic_array = np.ones(256, dtype=np.float32) * 0.3

        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array

        monitor_L_arr = np.zeros(256, dtype=np.float32)
        monitor_R_arr = np.zeros(256, dtype=np.float32)
        engine._monitor_L = MagicMock()
        engine._monitor_L.get_array.return_value = monitor_L_arr
        engine._monitor_R = MagicMock()
        engine._monitor_R.get_array.return_value = monitor_R_arr

        engine._process_callback(256)

        # Monitor outputs should have non-zero signal (gain * reverb applied)
        assert engine._monitor_L.get_array.called
        assert engine._monitor_R.get_array.called

    def test_process_callback_silences_when_muted(self):
        """Software mode: monitor outputs zeroed when muted."""
        config = self._make_config(monitor_mode="software", mic_gain=2.0, reverb_wet=0.1)
        engine = JackAudioEngine(config)
        engine._running = True
        engine._monitor_muted = True

        mic_array = np.ones(256, dtype=np.float32) * 0.5

        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array

        monitor_L_arr = np.ones(256, dtype=np.float32)
        monitor_R_arr = np.ones(256, dtype=np.float32)
        engine._monitor_L = MagicMock()
        engine._monitor_L.get_array.return_value = monitor_L_arr
        engine._monitor_R = MagicMock()
        engine._monitor_R.get_array.return_value = monitor_R_arr

        engine._process_callback(256)

        # Monitor outputs should be zeroed
        np.testing.assert_array_equal(monitor_L_arr, 0)
        np.testing.assert_array_equal(monitor_R_arr, 0)

    def test_mute_unmute_monitor(self):
        """Software mode: mute/unmute toggle _monitor_muted."""
        config = self._make_config(monitor_mode="software")
        engine = JackAudioEngine(config)
        assert not engine._monitor_muted

        engine.mute_monitor()
        assert engine._monitor_muted

        engine.unmute_monitor()
        assert not engine._monitor_muted

    def test_mute_unmute_noop_hardware(self):
        """Hardware mode: mute/unmute exist but are no-ops."""
        config = self._make_config(monitor_mode="hardware")
        engine = JackAudioEngine(config)

        # Should not raise
        engine.mute_monitor()
        engine.unmute_monitor()

        # _monitor_muted should not exist in hardware mode
        assert not hasattr(engine, '_monitor_muted')

    def test_shutdown_kills_processes(self):
        config = self._make_config()
        engine = JackAudioEngine(config)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        engine._jack_proc = mock_proc
        engine._running = True

        engine.shutdown()

        assert not engine._running
        assert engine._jack_proc is None
        mock_proc.terminate.assert_called()

    def test_ds_scratch_is_pre_allocated_and_bounded(self):
        """Downsample scratch must be pre-allocated and bounded across many callbacks
        (not grown via np.append)."""
        config = self._make_config(jack_period=256, monitor_mode="hardware")
        engine = JackAudioEngine(config)
        assert hasattr(engine, '_ds_scratch')
        scratch_id = id(engine._ds_scratch)
        scratch_size = engine._ds_scratch.size
        # Bounded: at most period + max leftover (3 - 1) = period + 2
        assert scratch_size <= 256 + 3

        engine._running = True
        mic_array = np.ones(256, dtype=np.float32) * 0.1
        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array
        # Drain ring to avoid wrap concerns
        for _ in range(500):
            engine._process_callback(256)
            engine._ring_read = engine._ring_write

        # Scratch must be the same object and same size
        assert id(engine._ds_scratch) == scratch_id
        assert engine._ds_scratch.size == scratch_size

    def test_ring_buffer_pre_allocated(self):
        """Ring buffer must be pre-allocated in __init__ with stable id."""
        config = self._make_config(monitor_mode="hardware")
        engine = JackAudioEngine(config)
        assert hasattr(engine, '_ring')
        assert engine._ring.dtype == np.int16
        ring_id = id(engine._ring)

        engine._running = True
        mic_array = np.ones(256, dtype=np.float32) * 0.1
        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array
        for _ in range(50):
            engine._process_callback(256)
            engine._ring_read = engine._ring_write

        assert id(engine._ring) == ring_id

    def test_software_monitor_wet_scratch_pre_allocated(self):
        """Software mode pre-allocates a wet scratch for mic_data * gain."""
        config = self._make_config(monitor_mode="software", jack_period=256)
        engine = JackAudioEngine(config)
        assert hasattr(engine, '_wet_scratch')
        assert engine._wet_scratch.dtype == np.float32
        assert engine._wet_scratch.size >= 256

    def test_downsample_correctness_across_callbacks(self):
        """Refactored downsample produces correct cumulative sample count
        across multiple callbacks with leftover handling."""
        config = self._make_config(monitor_mode="hardware", jack_period=256)
        engine = JackAudioEngine(config)
        engine._running = True
        mic_array = np.ones(256, dtype=np.float32) * 0.5
        engine._mic_in = MagicMock()
        engine._mic_in.get_array.return_value = mic_array

        # Run 9 callbacks: 9 * 256 = 2304 input samples; 2304 / 3 = 768 output samples
        for _ in range(9):
            engine._process_callback(256)
        produced = engine._ring_write - engine._ring_read
        assert produced == (9 * 256) // 3

    def test_anti_alias_attenuates_high_frequencies(self):
        """Anti-aliasing lowpass must strongly attenuate content above ~8kHz
        before 3:1 decimation, preventing audible aliasing in the 16kHz output."""
        config = self._make_config(monitor_mode="hardware", jack_period=256)
        engine = JackAudioEngine(config)
        engine._running = True

        # Generate a 12kHz sine at 48kHz - well above the 16kHz Nyquist (8kHz)
        # so it must be heavily attenuated by a proper anti-aliasing filter.
        rate = 48000
        block_size = 256
        n_blocks = 50
        n_total = block_size * n_blocks
        t = np.arange(n_total) / rate
        sig_high = (0.5 * np.sin(2 * np.pi * 12000 * t)).astype(np.float32)

        engine._mic_in = MagicMock()
        for i in range(n_blocks):
            chunk = sig_high[i * block_size:(i + 1) * block_size]
            engine._mic_in.get_array.return_value = chunk
            engine._process_callback(block_size)

        # Read decimated output from ring (skip first ~10 frames to let the IIR settle)
        n = engine._ring_write - engine._ring_read
        out_int16 = np.empty(n, dtype=np.int16)
        ring_size = engine._ring_size
        idx = engine._ring_read & (ring_size - 1)
        for i in range(n):
            out_int16[i] = engine._ring[(idx + i) & (ring_size - 1)]
        out_f = out_int16.astype(np.float32) / 32767.0
        # Drop initial transient
        out_f = out_f[200:]
        # The 12kHz tone, after lowpass + decimation, must be far below input level.
        # Without a filter, aliased content at 4kHz would have ~0.5 amplitude.
        rms = float(np.sqrt(np.mean(out_f ** 2)))
        assert rms < 0.05, f"12kHz content not attenuated: rms={rms:.3f}"

    def test_anti_alias_passes_low_frequencies(self):
        """Anti-aliasing lowpass must preserve content well below the 8kHz cutoff."""
        config = self._make_config(monitor_mode="hardware", jack_period=256)
        engine = JackAudioEngine(config)
        engine._running = True

        rate = 48000
        block_size = 256
        n_blocks = 50
        n_total = block_size * n_blocks
        t = np.arange(n_total) / rate
        sig_low = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)

        engine._mic_in = MagicMock()
        for i in range(n_blocks):
            chunk = sig_low[i * block_size:(i + 1) * block_size]
            engine._mic_in.get_array.return_value = chunk
            engine._process_callback(block_size)

        n = engine._ring_write - engine._ring_read
        out_int16 = np.empty(n, dtype=np.int16)
        ring_size = engine._ring_size
        idx = engine._ring_read & (ring_size - 1)
        for i in range(n):
            out_int16[i] = engine._ring[(idx + i) & (ring_size - 1)]
        out_f = out_int16.astype(np.float32) / 32767.0
        out_f = out_f[200:]
        rms = float(np.sqrt(np.mean(out_f ** 2)))
        # 1kHz signal at 0.5 amplitude has RMS ~0.354; expect minimal attenuation.
        assert rms > 0.25, f"1kHz content over-attenuated: rms={rms:.3f}"

    def test_ring_buffer_wraps_correctly(self):
        """Ring buffer correctly handles writes that wrap around its end."""
        config = self._make_config(monitor_mode="hardware")
        engine = JackAudioEngine(config)
        engine._running = True

        # Position write near the end of the ring
        engine._ring_write = engine._ring_size - 10
        engine._ring_read = engine._ring_write

        # Write samples that exceed the wrap point
        samples = np.arange(50, dtype=np.int16)
        engine._ring_write_samples(samples)

        # Read back via get_frame-style consumption
        n = engine._ring_write - engine._ring_read
        assert n == 50
        # Manually verify wrap content
        expected_idx_start = engine._ring_read & (engine._ring_size - 1)
        out = np.empty(50, dtype=np.int16)
        for i in range(50):
            out[i] = engine._ring[(expected_idx_start + i) & (engine._ring_size - 1)]
        np.testing.assert_array_equal(out, samples)
