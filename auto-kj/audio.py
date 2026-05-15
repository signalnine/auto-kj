"""JACK audio engine for mic capture and 16kHz frame output."""

import os
import subprocess
import threading
import time

import numpy as np
from scipy.signal import butter, lfilter, resample_poly

JACK_RATE = 48000
JACK_PERIOD = 256
OUTPUT_RATE = 16000
FRAME_SIZE = 1280  # 80ms at 16kHz


class SchroederReverb:
    """Simple Schroeder reverb: 4 comb filters + 2 allpass filters.

    Operates on float32 mono blocks at 48kHz.
    Uses scipy.signal.lfilter for C-optimized inner loops.
    """

    def __init__(self, rate: int = JACK_RATE, wet: float = 0.3):
        self.wet = wet
        # Comb filter delays (in samples) tuned for 48kHz
        comb_delays = [int(d * rate / 44100) for d in [1557, 1617, 1491, 1422]]
        comb_gains = [0.74, 0.71, 0.68, 0.65]
        # Comb filter: y[n] = x[n-D] + g*y[n-D]
        # Transfer: z^{-D} / (1 - g*z^{-D})
        # b = [0,0,...,0,1] (length D+1), a = [1,0,...,0,-g] (length D+1)
        self._combs = []
        for d, g in zip(comb_delays, comb_gains):
            b = np.zeros(d + 1)
            b[d] = 1.0
            a = np.zeros(d + 1)
            a[0] = 1.0
            a[d] = -g
            zi = np.zeros(d)
            self._combs.append((b, a, zi))

        # Scratch buffers, lazy-allocated on first process() call (block size
        # is fixed by JACK period). These let the RT callback avoid np.zeros
        # allocations on every block.
        self._scratch_size = 0
        self._comb_sum = None
        self._scaled_sig = None
        self._result_f64 = None
        self._result_f32 = None

        # Allpass filter delays
        ap_delays = [int(d * rate / 44100) for d in [225, 556]]
        ap_gain = 0.5
        # Allpass: y[n] = -g*x[n] + (1+g^2)*x[n-D] + g*y[n-D] - g^2*x[n-D] ... wait
        # From the original code:
        #   delayed = buf[pos]          # x[n-D] stored in circular buffer
        #   buf[pos] = sig[j] + g * delayed   # store for future: x[n] + g*x[n-D]
        #   out[j] = delayed - g * sig[j]     # output: x[n-D] - g*x[n]
        # This is a standard allpass: H(z) = (z^{-D} - g) / (1 - g*z^{-D})
        # But the buffer stores sig[j] + g*delayed, so the "delayed" read next time
        # is actually the stored value, not the raw input.
        # Let s[n] = buf contents. s[n] = x[n] + g*s[n-D]. out[n] = s[n-D] - g*x[n].
        # s[n] is a comb filter of x: S(z) = X(z)/(1 - g*z^{-D})
        # out[n] = s[n-D] - g*x[n] = z^{-D}*S(z) - g*X(z)
        #        = z^{-D}*X/(1-g*z^{-D}) - g*X = X*(z^{-D} - g)/(1-g*z^{-D})
        # So: b = [-g, 0,...,0, 1] (length D+1), a = [1, 0,...,0, -g] (length D+1)
        self._allpasses = []
        for d in ap_delays:
            b = np.zeros(d + 1)
            b[0] = -ap_gain
            b[d] = 1.0
            a = np.zeros(d + 1)
            a[0] = 1.0
            a[d] = -ap_gain
            zi = np.zeros(d)
            self._allpasses.append((b, a, zi))

    def _ensure_scratch(self, n: int) -> None:
        if self._scratch_size != n:
            self._comb_sum = np.zeros(n, dtype=np.float64)
            self._scaled_sig = np.zeros(n, dtype=np.float64)
            self._result_f64 = np.zeros(n, dtype=np.float64)
            self._result_f32 = np.zeros(n, dtype=np.float32)
            self._scratch_size = n

    def process(self, block: np.ndarray) -> np.ndarray:
        """Process a mono float32 block, return wet/dry mix.

        Steady-state allocations are limited to lfilter outputs (4 comb + 2
        allpass per block); all other arrays are pre-allocated scratch.
        """
        if self.wet <= 0:
            return block

        n = len(block)
        self._ensure_scratch(n)
        comb_sum = self._comb_sum
        comb_sum[:] = 0.0

        # Parallel comb filters
        for i, (b, a, zi) in enumerate(self._combs):
            out, zi_new = lfilter(b, a, block, zi=zi)
            self._combs[i] = (b, a, zi_new)
            comb_sum += out

        # Normalize comb sum to prevent clipping
        comb_sum *= 0.25
        # Series allpass filters
        sig = comb_sum
        for i, (b, a, zi) in enumerate(self._allpasses):
            sig, zi_new = lfilter(b, a, sig, zi=zi)
            self._allpasses[i] = (b, a, zi_new)

        # result_f64 = block*(1-wet) + sig*wet, all in pre-allocated buffers
        result = self._result_f64
        np.multiply(block, 1.0 - self.wet, out=result)
        np.multiply(sig, self.wet, out=self._scaled_sig)
        result += self._scaled_sig
        np.clip(result, -1.0, 1.0, out=result)
        np.copyto(self._result_f32, result, casting='unsafe')
        return self._result_f32


class JackAudioEngine:
    """Manages JACK server and provides downsampled 16kHz frames for
    wakeword/whisper."""

    # Output ring buffer size in 16kHz int16 samples (~2s at 16kHz).
    # Power of 2 to allow bitmask wraparound.
    _RING_SIZE = 32768
    _RING_MASK = _RING_SIZE - 1

    def __init__(self, config):
        self._config = config
        self._jack_proc: subprocess.Popen | None = None
        self._client = None

        period = config.jack_period

        # Software monitoring (SchroederReverb through JACK monitor ports)
        self._software_monitor = config.monitor_mode == "software"
        if self._software_monitor:
            self._reverb = SchroederReverb(JACK_RATE, config.reverb_wet)
            self._gain = config.mic_gain
            self._monitor_muted = False
            # Pre-allocated scratch for `mic_data * gain` so the RT callback
            # does not allocate a temporary array per block.
            self._wet_scratch = np.zeros(period, dtype=np.float32)

        # Downsample input scratch: holds at most (period + leftover) float32
        # samples at 48kHz. Leftover is at most 2 (for 3:1 ratio), so size
        # period + 3 is a safe upper bound. Pre-allocated to avoid np.append
        # in the JACK process callback.
        self._ds_scratch = np.zeros(period + 3, dtype=np.float32)
        self._ds_leftover_n = 0
        # Float32 scratch for downsample output before int16 quantization.
        self._ds_f32_scratch = np.zeros(period // 3 + 2, dtype=np.float32)

        # Anti-aliasing lowpass for 48kHz -> 16kHz decimation. Cutoff ~7.5kHz
        # (below the 16kHz Nyquist of 8kHz) prevents fold-back aliasing that
        # would otherwise smear sibilants and degrade wakeword/Whisper accuracy.
        # 4th-order Butterworth keeps the filter cheap (one extra lfilter call
        # per JACK callback).
        self._aa_b, self._aa_a = butter(N=4, Wn=7500.0 / (JACK_RATE / 2), btype='low')
        self._aa_zi = np.zeros(max(len(self._aa_a), len(self._aa_b)) - 1, dtype=np.float64)

        # Output ring buffer for downsampled int16 samples. The producer is
        # the JACK process callback; the consumer is get_frame(). The ring
        # is pre-allocated so no per-callback allocation is needed.
        self._ring_size = self._RING_SIZE
        self._ring = np.zeros(self._ring_size, dtype=np.int16)
        self._ring_write = 0  # monotonic counter; index = & _RING_MASK
        self._ring_read = 0
        self._ring_lock = threading.Lock()
        self._frame_event = threading.Event()

        self._running = False

    def start(self):
        """Start JACK server and register JACK client."""
        self._running = True
        self._start_jackd()
        self._wait_for_jack()
        time.sleep(0.5)
        self._start_client()
        mode = "software" if self._software_monitor else "hardware"
        print(f"[audio] monitor mode: {mode}")

    def _wait_for_jack(self, timeout: float = 10.0):
        """Poll until JACK server is accepting connections."""
        import jack
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                c = jack.Client("auto-kj-probe", no_start_server=True)
                c.close()
                print("[audio] JACK server ready")
                return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("JACK server did not start within timeout")

    def _start_jackd(self):
        device = self._config.jack_device
        mic_device = self._config.jack_mic_device
        period = self._config.jack_period
        env = {**os.environ, "JACK_NO_AUDIO_RESERVATION": "1"}
        self._jack_proc = subprocess.Popen(
            [
                "jackd", "-R", "-d", "alsa",
                "-P", device,
                "-C", mic_device,
                "-r", str(JACK_RATE),
                "-p", str(period),
                "-n", "2",
                "-S",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env,
        )
        print(f"[audio] jackd started (playback={device}, capture={mic_device}, period={period})")

    def _start_client(self):
        import jack

        client = jack.Client("auto-kj", no_start_server=True)
        client.set_process_callback(self._process_callback)
        client.set_shutdown_callback(self._shutdown_callback)

        # Register ports
        self._mic_in = client.inports.register("mic_in")
        if self._software_monitor:
            self._monitor_L = client.outports.register("monitor_L")
            self._monitor_R = client.outports.register("monitor_R")

        client.activate()
        self._client = client

        # Connect ports after a brief settle
        time.sleep(0.3)
        self._connect_ports()

    def _connect_ports(self):
        client = self._client
        try:
            # system capture -> our mic input
            capture_ports = client.get_ports("system", is_output=True, is_audio=True)
            if capture_ports:
                client.connect(capture_ports[0], self._mic_in)
                print(f"[audio] connected {capture_ports[0].name} -> auto-kj:mic_in")

            # Software mode: connect monitor outputs -> system playback
            if self._software_monitor:
                sys_play = client.get_ports("system", is_input=True, is_audio=True)
                if len(sys_play) >= 2:
                    client.connect(self._monitor_L, sys_play[0])
                    client.connect(self._monitor_R, sys_play[1])
                    print(f"[audio] connected monitor -> {sys_play[0].name}, {sys_play[1].name}")
        except Exception as e:
            print(f"[audio] port connection warning: {e}")

    def _process_callback(self, frames):
        """JACK real-time callback: downsample mic input to 16kHz frames.

        Steady-state allocations are limited to lfilter outputs inside
        SchroederReverb.process; all other buffers are pre-allocated.
        """
        mic_data = self._mic_in.get_array()

        # Software monitoring: apply gain+reverb to monitor outputs
        if self._software_monitor:
            if not self._monitor_muted:
                wet = self._wet_scratch[:frames]
                np.multiply(mic_data, self._gain, out=wet)
                processed = self._reverb.process(wet)
                self._monitor_L.get_array()[:] = processed
                self._monitor_R.get_array()[:] = processed
            else:
                self._monitor_L.get_array()[:] = 0
                self._monitor_R.get_array()[:] = 0

        # Anti-alias lowpass before decimation. lfilter allocates the output
        # array (acceptable per the RT criteria); state is carried across
        # callbacks via self._aa_zi.
        filtered, self._aa_zi = lfilter(
            self._aa_b, self._aa_a, mic_data, zi=self._aa_zi
        )

        # Downsample 48kHz -> 16kHz (3:1 ratio) using fixed scratch buffer.
        leftover = self._ds_leftover_n
        n_in = leftover + frames
        scratch = self._ds_scratch
        # Append new (filtered) mic samples after any leftover from prior callback.
        scratch[leftover:n_in] = filtered
        n_out = n_in // 3
        consumed = n_out * 3
        # Move tail leftover to start of scratch for next callback.
        new_leftover = n_in - consumed
        if n_out > 0:
            # Take every 3rd sample (view, no allocation).
            src = scratch[:consumed:3]
            f32_out = self._ds_f32_scratch[:n_out]
            np.multiply(src, 32767.0, out=f32_out)
            np.clip(f32_out, -32768.0, 32767.0, out=f32_out)
            self._ring_write_samples_f32(f32_out)
            self._frame_event.set()
        if new_leftover > 0:
            # Slide remainder down. Use a copy to avoid overlapping view issues.
            scratch[:new_leftover] = scratch[consumed:n_in]
        self._ds_leftover_n = new_leftover

    def _ring_write_samples_f32(self, f32_samples: np.ndarray) -> None:
        """Cast float32 samples to int16 and write to the ring buffer."""
        n = f32_samples.size
        ring = self._ring
        size = self._ring_size
        write = self._ring_write
        idx = write & self._RING_MASK
        end = idx + n
        if end <= size:
            np.copyto(ring[idx:end], f32_samples, casting='unsafe')
        else:
            first = size - idx
            np.copyto(ring[idx:size], f32_samples[:first], casting='unsafe')
            np.copyto(ring[:n - first], f32_samples[first:], casting='unsafe')
        self._ring_write = write + n

    def _ring_write_samples(self, samples: np.ndarray) -> None:
        """Write int16 samples to the ring buffer (used by tests)."""
        n = samples.size
        ring = self._ring
        size = self._ring_size
        write = self._ring_write
        idx = write & self._RING_MASK
        end = idx + n
        if end <= size:
            ring[idx:end] = samples
        else:
            first = size - idx
            ring[idx:size] = samples[:first]
            ring[:n - first] = samples[first:]
        self._ring_write = write + n

    def _shutdown_callback(self, status, reason):
        print(f"[audio] JACK shutdown: {reason}")
        self._running = False

    def get_frame(self) -> np.ndarray | None:
        """Return a 1280-sample int16 frame at 16kHz, blocking until available.

        Returns None if the engine is stopped.
        """
        while self._running:
            with self._ring_lock:
                available = self._ring_write - self._ring_read
            if available >= FRAME_SIZE:
                return self._read_frame(FRAME_SIZE)
            self._frame_event.wait(timeout=0.1)
            self._frame_event.clear()
        return None

    def _read_frame(self, n: int) -> np.ndarray:
        """Copy n samples out of the ring buffer, advancing the read pointer."""
        ring = self._ring
        size = self._ring_size
        read = self._ring_read
        idx = read & self._RING_MASK
        end = idx + n
        out = np.empty(n, dtype=np.int16)
        if end <= size:
            out[:] = ring[idx:end]
        else:
            first = size - idx
            out[:first] = ring[idx:size]
            out[first:] = ring[:n - first]
        with self._ring_lock:
            self._ring_read = read + n
        return out

    def mute_monitor(self):
        """Mute mic monitoring (e.g. during TTS to prevent feedback)."""
        if self._software_monitor:
            self._monitor_muted = True

    def unmute_monitor(self):
        """Unmute mic monitoring."""
        if self._software_monitor:
            self._monitor_muted = False

    def play_buffer(self, audio_data: np.ndarray, source_rate: int):
        """Play an audio buffer through JACK (used for TTS).

        Creates a short-lived JACK client to play the buffer, resampling
        from source_rate to 48kHz.
        """
        import jack

        # Normalize to float32 before resampling so polyphase math runs on
        # floats and the int16 dynamic range isn't corrupted by anti-alias
        # filter ringing.
        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0

        # Resample to 48kHz via polyphase (scipy.signal.resample_poly) so the
        # anti-alias filter rolls off above the source Nyquist; the previous
        # nearest-neighbor integer indexing produced zero-order-hold artifacts.
        if source_rate != JACK_RATE:
            g = np.gcd(int(JACK_RATE), int(source_rate))
            up = int(JACK_RATE) // g
            down = int(source_rate) // g
            audio_data = resample_poly(audio_data, up, down).astype(np.float32)

        # Play through a short-lived JACK client
        pos = 0
        done_event = threading.Event()

        client = jack.Client("auto-kj-tts", no_start_server=True)
        out_L = client.outports.register("out_L")
        out_R = client.outports.register("out_R")

        # Pre-allocated scratch for the partial-tail pad. Sized lazily on the
        # first partial callback so we don't need the JACK period up front;
        # reused thereafter so the JACK RT callback does no allocations.
        pad_scratch: list[np.ndarray | None] = [None]

        def tts_callback(frames):
            nonlocal pos
            chunk = audio_data[pos:pos + frames]
            if len(chunk) < frames:
                padded = pad_scratch[0]
                if padded is None or padded.size != frames:
                    padded = np.zeros(frames, dtype=np.float32)
                    pad_scratch[0] = padded
                padded[:len(chunk)] = chunk
                padded[len(chunk):] = 0.0
                out_L.get_array()[:] = padded
                out_R.get_array()[:] = padded
                done_event.set()
            else:
                out_L.get_array()[:] = chunk
                out_R.get_array()[:] = chunk
            pos += frames

        client.set_process_callback(tts_callback)
        client.activate()

        # Connect to system playback
        try:
            sys_play = client.get_ports("system", is_input=True, is_audio=True)
            if len(sys_play) >= 2:
                client.connect(out_L, sys_play[0])
                client.connect(out_R, sys_play[1])
        except Exception:
            pass

        # Wait for playback to complete
        duration = len(audio_data) / JACK_RATE
        done_event.wait(timeout=duration + 1.0)
        # Brief tail to let last buffer drain
        time.sleep(0.05)
        client.deactivate()
        client.close()

    def shutdown(self):
        """Stop JACK client and server."""
        self._running = False
        if self._client:
            try:
                self._client.deactivate()
                self._client.close()
            except Exception:
                pass
            self._client = None
        if self._jack_proc and self._jack_proc.poll() is None:
            try:
                self._jack_proc.terminate()
                self._jack_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._jack_proc.kill()
        self._jack_proc = None
        print("[audio] JACK engine stopped")
