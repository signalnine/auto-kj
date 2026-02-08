"""auto-kj: Voice-controlled karaoke machine."""

import os
import sys
import time
import threading
import numpy as np
import pyaudio

from config import Config
from state import KaraokeState, StateMachine
from queue_manager import SongQueue
from playback import Player
from keyboard import KeyboardHandler
from songs.cache import SongCache
from songs.pipeline import SongPipeline
from voice.wakeword import WakeWordListener
from voice.transcribe import transcribe_audio
from voice.commands import parse_command
from voice.tts import speak

SAMPLE_RATE = 16000
FRAME_SIZE = 1280  # 80ms at 16kHz


class Karaoke:
    def __init__(self, config: Config):
        self.config = config
        self.sm = StateMachine()
        self.queue = SongQueue()
        self.player = Player()
        self.cache = SongCache(config.cache_dir, config.cache_max_bytes)
        self.pipeline = SongPipeline(self.cache, self.queue, speak, config.cache_dir)
        self.wakeword = WakeWordListener()
        self.keyboard = KeyboardHandler()
        self._running = False
        self._audio = pyaudio.PyAudio()
        self._recording = False
        self._record_frames: list[np.ndarray] = []

        self._setup_callbacks()

    def _setup_callbacks(self):
        self.player.on_song_end(self._on_song_end)
        self.keyboard.on("space", self._on_spacebar)
        self.keyboard.on("escape", self._on_escape)
        self.keyboard.on("up", self.player.volume_up)
        self.keyboard.on("down", self.player.volume_down)
        self.keyboard.on("q", self.shutdown)

    def _on_song_end(self):
        song = self.queue.next()
        if song:
            self.sm.transition(KaraokeState.IDLE)
            self.sm.transition(KaraokeState.PLAYING)
            self.player.play(song)
        else:
            self.sm.transition(KaraokeState.IDLE)
            speak("Queue is empty. What should I play next?")

    def _on_spacebar(self):
        if self.sm.state == KaraokeState.PLAYING:
            self.player.pause()
            self.sm.transition(KaraokeState.LISTENING)
            self._listen_for_command()
        elif self.sm.state in (KaraokeState.IDLE, KaraokeState.PAUSED):
            self.sm.transition(KaraokeState.LISTENING)
            self._listen_for_command()

    def _on_escape(self):
        if self.sm.state == KaraokeState.PLAYING:
            self.player.skip()

    def _listen_for_command(self):
        """Start recording from the shared mic stream, then process."""
        self._record_frames = []
        self._recording = True
        threading.Thread(target=self._wait_and_process, daemon=True).start()

    def _wait_and_process(self):
        """Wait for recording to complete, then transcribe and act."""
        max_frames = int(SAMPLE_RATE * 5 / FRAME_SIZE)
        while len(self._record_frames) < max_frames and self._recording:
            time.sleep(0.05)
        self._recording = False

        if not self._record_frames:
            self.sm.return_from_listening()
            return

        audio = np.concatenate(self._record_frames)
        text = transcribe_audio(audio, SAMPLE_RATE, self.config.whisper_model)
        if not text:
            self.sm.return_from_listening()
            return

        speak(f"I heard: {text}")
        intent, song = parse_command(text)
        self._handle_intent(intent, song)

    def _handle_intent(self, intent: str, song: str | None):
        if intent == "play" and song:
            self.pipeline.request(song)
            if self.sm.state == KaraokeState.LISTENING:
                self.sm.return_from_listening()
            self._try_start_playback()
        elif intent == "skip":
            self.sm.return_from_listening()
            self.player.skip()
        elif intent == "pause":
            if self.sm.state == KaraokeState.LISTENING:
                self.sm.return_from_listening()
        elif intent == "resume":
            self.player.resume()
            self.sm.return_from_listening()
            if self.sm.state == KaraokeState.PAUSED:
                self.sm.transition(KaraokeState.PLAYING)
        elif intent == "queue":
            songs = self.queue.list()
            if songs:
                titles = ", ".join(s["title"] for s in songs[:5])
                speak(f"Up next: {titles}")
            else:
                speak("Queue is empty")
            self.sm.return_from_listening()
        elif intent == "volume_up":
            self.player.volume_up()
            self.sm.return_from_listening()
        elif intent == "volume_down":
            self.player.volume_down()
            self.sm.return_from_listening()
        elif intent == "cancel":
            self.sm.return_from_listening()
        else:
            speak("Sorry, I didn't understand that")
            self.sm.return_from_listening()

    def _try_start_playback(self):
        """Check queue and start playing if idle."""
        def _check():
            time.sleep(2)
            for _ in range(30):
                if self.sm.state == KaraokeState.IDLE and not self.queue.is_empty():
                    song = self.queue.next()
                    if song:
                        self.sm.transition(KaraokeState.PLAYING)
                        self.player.play(song)
                    return
                time.sleep(2)
        threading.Thread(target=_check, daemon=True).start()

    def _mic_loop(self):
        """Single shared mic stream for both wakeword and command recording.

        Always-on stream avoids ALSA device contention. Frames are routed to
        either wakeword detection or command recording based on current state.
        """
        stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=FRAME_SIZE,
        )
        while self._running:
            data = stream.read(FRAME_SIZE, exception_on_overflow=False)
            frame = np.frombuffer(data, dtype=np.int16)

            if self._recording:
                # Route frames to command recording buffer
                self._record_frames.append(frame)
                continue

            if self.sm.state in (KaraokeState.IDLE, KaraokeState.PAUSED):
                # Route frames to wakeword detection
                if self.wakeword.process_frame(frame):
                    self.wakeword.reset()
                    self.sm.transition(KaraokeState.LISTENING)
                    self._listen_for_command()

        stream.stop_stream()
        stream.close()

    def run(self):
        self._running = True
        os.makedirs(self.config.cache_dir, exist_ok=True)
        speak("Karaoke machine ready. Say Hey Karaoke or press spacebar.")

        self.keyboard.start()
        threading.Thread(target=self._mic_loop, daemon=True).start()

        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.shutdown()

    def shutdown(self):
        self._running = False
        self.player.shutdown()
        self._audio.terminate()
        speak("Goodbye!")
        time.sleep(1)
        sys.exit(0)


def _update_ytdlp():
    """Update yt-dlp to latest version on startup."""
    import subprocess
    try:
        subprocess.run(
            ["uv", "pip", "install", "-U", "yt-dlp"],
            capture_output=True, timeout=60,
        )
    except Exception:
        pass  # non-fatal, use whatever version is installed


def main():
    _update_ytdlp()
    config = Config()
    karaoke = Karaoke(config)
    karaoke.run()


if __name__ == "__main__":
    main()
