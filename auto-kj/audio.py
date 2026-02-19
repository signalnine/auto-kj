"""JACK audio engine for mic capture and 16kHz frame output."""

import os
import subprocess
import threading
import time

import numpy as np
from scipy.signal import lfilter

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

    def process(self, block: np.ndarray) -> np.ndarray:
        """Process a mono float32 block, return wet/dry mix."""
        if self.wet <= 0:
            return block

        n = len(block)
        comb_sum = np.zeros(n, dtype=np.float64)

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

        result = block * (1.0 - self.wet) + sig * self.wet
        return np.clip(result, -1.0, 1.0).astype(np.float32)


class JackAudioEngine:
    """Manages JACK server and provides downsampled 16kHz frames for
    wakeword/whisper."""

    def __init__(self, config):
        self._config = config
        self._jack_proc: subprocess.Popen | None = None
        self._client = None

        # Software monitoring (SchroederReverb through JACK monitor ports)
        self._software_monitor = config.monitor_mode == "software"
        if self._software_monitor:
            self._reverb = SchroederReverb(JACK_RATE, config.reverb_wet)
            self._gain = config.mic_gain
            self._monitor_muted = False

        # Downsample buffer: accumulate 48kHz samples, output 16kHz frames
        self._ds_buf = np.array([], dtype=np.float32)
        self._frame_buf: list[np.ndarray] = []
        self._frame_lock = threading.Lock()
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
        """JACK real-time callback: downsample mic input to 16kHz frames."""
        mic_data = self._mic_in.get_array()

        # Software monitoring: apply gain+reverb to monitor outputs
        if self._software_monitor:
            if not self._monitor_muted:
                wet = mic_data * self._gain
                wet = self._reverb.process(wet)
                self._monitor_L.get_array()[:] = wet
                self._monitor_R.get_array()[:] = wet
            else:
                self._monitor_L.get_array()[:] = 0
                self._monitor_R.get_array()[:] = 0

        # Downsample 48kHz -> 16kHz (3:1 ratio) and buffer frames
        self._ds_buf = np.append(self._ds_buf, mic_data)
        # Take every 3rd sample for 3:1 downsampling
        n_out = len(self._ds_buf) // 3
        if n_out > 0:
            downsampled = self._ds_buf[:n_out * 3:3]
            self._ds_buf = self._ds_buf[n_out * 3:]
            # Convert to int16 for wakeword/whisper compatibility
            int16_data = np.clip(downsampled * 32767, -32768, 32767).astype(np.int16)
            with self._frame_lock:
                self._frame_buf.append(int16_data)
                self._frame_event.set()

    def _shutdown_callback(self, status, reason):
        print(f"[audio] JACK shutdown: {reason}")
        self._running = False

    def get_frame(self) -> np.ndarray | None:
        """Return a 1280-sample int16 frame at 16kHz, blocking until available.

        Returns None if the engine is stopped.
        """
        accumulated = np.array([], dtype=np.int16)
        while self._running:
            self._frame_event.wait(timeout=0.1)
            self._frame_event.clear()
            with self._frame_lock:
                if self._frame_buf:
                    accumulated = np.concatenate([accumulated] + self._frame_buf)
                    self._frame_buf.clear()
            if len(accumulated) >= FRAME_SIZE:
                frame = accumulated[:FRAME_SIZE]
                # Put remainder back
                remainder = accumulated[FRAME_SIZE:]
                if len(remainder) > 0:
                    with self._frame_lock:
                        self._frame_buf.insert(0, remainder)
                return frame
        return None

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

        # Resample to 48kHz
        if source_rate != JACK_RATE:
            ratio = JACK_RATE / source_rate
            n_out = int(len(audio_data) * ratio)
            indices = np.arange(n_out) / ratio
            indices = np.clip(indices, 0, len(audio_data) - 1).astype(int)
            audio_data = audio_data[indices]

        # Normalize to float32
        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0

        # Play through a short-lived JACK client
        pos = 0
        done_event = threading.Event()

        client = jack.Client("auto-kj-tts", no_start_server=True)
        out_L = client.outports.register("out_L")
        out_R = client.outports.register("out_R")

        def tts_callback(frames):
            nonlocal pos
            chunk = audio_data[pos:pos + frames]
            if len(chunk) < frames:
                padded = np.zeros(frames, dtype=np.float32)
                padded[:len(chunk)] = chunk
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
