import os
import subprocess
import sys
import threading
import queue

import numpy as np

_PIPER_MODEL = os.path.expanduser("~/.auto-kj/piper/en_US-lessac-medium.onnx")
_PIPER_BIN = os.path.join(os.path.dirname(sys.executable), "piper")

_queue: queue.Queue[str | None] = queue.Queue()
_started = False
_start_lock = threading.Lock()

# Set by main.py to the JackAudioEngine instance
_audio_engine = None


def set_audio_engine(engine):
    """Register the JACK audio engine for playback and monitor muting."""
    global _audio_engine
    _audio_engine = engine


def _synth_piper(text: str) -> np.ndarray | None:
    """Synthesize text with Piper, return int16 numpy array or None."""
    try:
        proc = subprocess.run(
            [_PIPER_BIN, "--model", _PIPER_MODEL, "--output-raw"],
            input=text.encode(), capture_output=True, timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            return np.frombuffer(proc.stdout, dtype=np.int16)
    except Exception as e:
        print(f"[tts] piper error: {e}")
    return None


def _synth_espeak(text: str) -> np.ndarray | None:
    """Synthesize text with espeak-ng, return int16 numpy array or None."""
    try:
        proc = subprocess.run(
            ["espeak-ng", "--stdout", text],
            capture_output=True, timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            # espeak-ng --stdout produces WAV; skip 44-byte header
            return np.frombuffer(proc.stdout[44:], dtype=np.int16)
    except Exception as e:
        print(f"[tts] espeak error: {e}")
    return None


def _worker():
    while True:
        text = _queue.get()
        if text is None:
            break
        print(f"[tts] {text}")
        try:
            # Synthesize audio
            if os.path.exists(_PIPER_MODEL):
                audio = _synth_piper(text)
                source_rate = 22050
            else:
                audio = _synth_espeak(text)
                source_rate = 22050  # espeak-ng default

            if audio is None or len(audio) == 0:
                print(f"[tts] synth returned no audio")
                continue

            if _audio_engine:
                _audio_engine.mute_monitor()
                try:
                    _audio_engine.play_buffer(audio, source_rate)
                finally:
                    _audio_engine.unmute_monitor()
            else:
                # Fallback: pipe to aplay if no JACK engine
                subprocess.run(
                    ["aplay", "-q", "-r", str(source_rate), "-f", "S16_LE", "-c", "1"],
                    input=audio.tobytes(), timeout=30,
                )
        except Exception as e:
            print(f"[tts] error: {e}")
        finally:
            _queue.task_done()


def speak(text: str):
    global _started
    with _start_lock:
        if not _started:
            threading.Thread(target=_worker, daemon=True).start()
            _started = True
    _queue.put(text)


def wait_for_speech():
    """Block until all queued speech has been spoken."""
    _queue.join()
