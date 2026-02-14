"""JACK audio engine for mic capture and 16kHz frame output."""

import os
import subprocess
import threading
import time

import numpy as np

JACK_RATE = 48000
JACK_PERIOD = 256
OUTPUT_RATE = 16000
FRAME_SIZE = 1280  # 80ms at 16kHz


class JackAudioEngine:
    """Manages JACK server, zita-a2j bridge, and provides downsampled
    16kHz frames for wakeword/whisper."""

    def __init__(self, config):
        self._config = config
        self._jack_proc: subprocess.Popen | None = None
        self._zita_proc: subprocess.Popen | None = None
        self._client = None

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
        except Exception as e:
            print(f"[audio] port connection warning: {e}")

    def _process_callback(self, frames):
        """JACK real-time callback: downsample mic input to 16kHz frames."""
        mic_data = self._mic_in.get_array()

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
