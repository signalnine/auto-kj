#!/usr/bin/env python
"""CLI tool to speak text through JACK. Usage: python speak.py "hello world" """

import os
import subprocess
import sys
import threading
import time

import numpy as np
import jack

JACK_RATE = 48000
_PIPER_MODEL = os.path.expanduser("~/.auto-kj/piper/en_US-lessac-medium.onnx")
_PIPER_BIN = os.path.join(os.path.dirname(sys.executable), "piper")


def synth(text: str) -> np.ndarray:
    """Synthesize text, preferring piper over espeak-ng. Returns int16 array."""
    if os.path.exists(_PIPER_MODEL):
        proc = subprocess.run(
            [_PIPER_BIN, "--model", _PIPER_MODEL, "--output-raw"],
            input=text.encode(), capture_output=True, timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            return np.frombuffer(proc.stdout, dtype=np.int16)
    proc = subprocess.run(
        ["espeak-ng", "--stdout", text],
        capture_output=True, timeout=30,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"espeak-ng failed: {proc.stderr.decode()}")
    # WAV header is 44 bytes; espeak-ng outputs 22050Hz mono int16
    return np.frombuffer(proc.stdout[44:], dtype=np.int16)


def play(audio: np.ndarray, source_rate: int = 22050):
    """Play int16 audio through JACK."""
    # Resample to 48kHz
    ratio = JACK_RATE / source_rate
    n_out = int(len(audio) * ratio)
    indices = np.clip(np.arange(n_out) / ratio, 0, len(audio) - 1).astype(int)
    resampled = audio[indices].astype(np.float32) / 32768.0

    pos = 0
    done = threading.Event()

    client = jack.Client("auto-kj-speak", no_start_server=True)
    out_L = client.outports.register("out_L")
    out_R = client.outports.register("out_R")

    def callback(frames):
        nonlocal pos
        chunk = resampled[pos:pos + frames]
        if len(chunk) < frames:
            buf = np.zeros(frames, dtype=np.float32)
            buf[:len(chunk)] = chunk
            out_L.get_array()[:] = buf
            out_R.get_array()[:] = buf
            done.set()
        else:
            out_L.get_array()[:] = chunk
            out_R.get_array()[:] = chunk
        pos += frames

    client.set_process_callback(callback)
    client.activate()

    for port in client.get_ports("system", is_input=True, is_audio=True)[:2]:
        if "1" in port.name:
            client.connect(out_L, port)
        else:
            client.connect(out_R, port)

    done.wait(timeout=len(resampled) / JACK_RATE + 1.0)
    time.sleep(0.05)
    client.deactivate()
    client.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python speak.py \"text to speak\"")
        sys.exit(1)
    text = " ".join(sys.argv[1:])
    audio = synth(text)
    play(audio)
