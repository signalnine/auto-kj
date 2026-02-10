"""JACK audio engine for mic monitoring with reverb and 16kHz frame output."""

import os
import subprocess
import threading
import time

import numpy as np

JACK_RATE = 48000
JACK_PERIOD = 256
OUTPUT_RATE = 16000
FRAME_SIZE = 1280  # 80ms at 16kHz


class SchroederReverb:
    """Simple Schroeder reverb: 4 comb filters + 2 allpass filters.

    Operates on float32 mono blocks at 48kHz.
    """

    def __init__(self, rate: int = JACK_RATE, wet: float = 0.3):
        self.wet = wet
        # Comb filter delays (in samples) tuned for 48kHz
        comb_delays = [int(d * rate / 44100) for d in [1557, 1617, 1491, 1422]]
        comb_gains = [0.84, 0.80, 0.77, 0.74]
        self._combs = [
            (np.zeros(d, dtype=np.float32), d, g, 0)
            for d, g in zip(comb_delays, comb_gains)
        ]
        # Allpass filter delays
        ap_delays = [int(d * rate / 44100) for d in [225, 556]]
        ap_gain = 0.5
        self._allpasses = [
            (np.zeros(d, dtype=np.float32), d, ap_gain, 0)
            for d in ap_delays
        ]

    def process(self, block: np.ndarray) -> np.ndarray:
        """Process a mono float32 block, return wet/dry mix."""
        if self.wet <= 0:
            return block

        n = len(block)
        comb_sum = np.zeros(n, dtype=np.float32)

        # Parallel comb filters
        for i, (buf, delay, gain, pos) in enumerate(self._combs):
            out = np.empty(n, dtype=np.float32)
            for j in range(n):
                out[j] = buf[pos]
                buf[pos] = block[j] + gain * buf[pos]
                pos = (pos + 1) % delay
            self._combs[i] = (buf, delay, gain, pos)
            comb_sum += out

        # Series allpass filters
        sig = comb_sum
        for i, (buf, delay, gain, pos) in enumerate(self._allpasses):
            out = np.empty(n, dtype=np.float32)
            for j in range(n):
                delayed = buf[pos]
                buf[pos] = sig[j] + gain * delayed
                out[j] = delayed - gain * sig[j]
                pos = (pos + 1) % delay
            self._allpasses[i] = (buf, delay, gain, pos)
            sig = out

        return block * (1.0 - self.wet) + sig * self.wet


class JackAudioEngine:
    """Manages JACK server, zita-a2j bridge, mic monitoring with reverb,
    and provides downsampled 16kHz frames for wakeword/whisper."""

    def __init__(self, config):
        self._config = config
        self._jack_proc: subprocess.Popen | None = None
        self._zita_proc: subprocess.Popen | None = None
        self._client = None
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
        """Start JACK server, zita-a2j bridge, and register JACK client."""
        self._running = True
        self._start_jackd()
        self._wait_for_jack()
        self._start_zita()
        time.sleep(0.5)
        self._start_client()

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
        period = self._config.jack_period
        env = {**os.environ, "JACK_NO_AUDIO_RESERVATION": "1"}
        self._jack_proc = subprocess.Popen(
            [
                "jackd", "-R", "-d", "alsa",
                "-P", device,
                "-r", str(JACK_RATE),
                "-p", str(period),
                "-n", "2",
                "-S",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env,
        )
        print(f"[audio] jackd started (playback={device}, period={period})")

    def _start_zita(self):
        mic_device = self._config.jack_mic_device
        self._zita_proc = subprocess.Popen(
            [
                "zita-a2j", "-d", mic_device,
                "-r", str(JACK_RATE),
                "-p", str(JACK_PERIOD),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"[audio] zita-a2j started (mic={mic_device})")

    def _start_client(self):
        import jack

        client = jack.Client("auto-kj", no_start_server=True)
        client.set_process_callback(self._process_callback)
        client.set_shutdown_callback(self._shutdown_callback)

        # Register ports
        self._mic_in = client.inports.register("mic_in")
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
            # zita-a2j capture -> our mic input
            zita_ports = client.get_ports("zita-a2j", is_output=True)
            if zita_ports:
                client.connect(zita_ports[0], self._mic_in)
                print(f"[audio] connected {zita_ports[0].name} -> auto-kj:mic_in")

            # Our monitor outputs -> system playback
            sys_play = client.get_ports("system", is_input=True, is_audio=True)
            if len(sys_play) >= 2:
                client.connect(self._monitor_L, sys_play[0])
                client.connect(self._monitor_R, sys_play[1])
                print(f"[audio] connected monitor -> {sys_play[0].name}, {sys_play[1].name}")
        except Exception as e:
            print(f"[audio] port connection warning: {e}")

    def _process_callback(self, frames):
        """JACK real-time callback: reverb mic -> monitor, downsample -> frame buf."""
        mic_data = self._mic_in.get_array()

        # Apply gain and reverb for monitoring
        if not self._monitor_muted and self._config.monitor_enabled:
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
        self._monitor_muted = True

    def unmute_monitor(self):
        """Unmute mic monitoring."""
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
        for proc in (self._zita_proc, self._jack_proc):
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._zita_proc = None
        self._jack_proc = None
        print("[audio] JACK engine stopped")
