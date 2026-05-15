"""auto-kj: Voice-controlled karaoke machine."""

import os
import sys
import time
import wave
import threading
import collections
from datetime import datetime
import numpy as np

from audio import JackAudioEngine, OUTPUT_RATE, FRAME_SIZE
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
from voice.tts import speak, set_audio_engine


class Karaoke:
    def __init__(self, config: Config):
        self.config = config
        self.sm = StateMachine()
        self.queue = SongQueue()
        self.player = Player()
        self.cache = SongCache(config.cache_dir, config.cache_max_bytes)
        self.pipeline = SongPipeline(self.cache, self.queue, speak, config.cache_dir)
        self.wakeword = WakeWordListener(model_path=config.wakeword_model)
        self.keyboard = KeyboardHandler()
        self._running = False
        self._audio = JackAudioEngine(config)
        self._recording = False
        self._record_frames: list[np.ndarray] = []
        self._clip_buffer: collections.deque[np.ndarray] = collections.deque(maxlen=25)

        self._setup_callbacks()

    def _setup_callbacks(self):
        self.player.on_song_end(self._on_song_end)
        self.queue.on_add(self._on_queue_song_added)
        # Spacebar pauses mpv to free the mic; unpause on every return to PLAYING.
        self.sm.on_enter(KaraokeState.PLAYING, self.player.resume)
        self.keyboard.on("space", self._on_spacebar)
        self.keyboard.on("escape", self._on_escape)
        self.keyboard.on("up", self.player.volume_up)
        self.keyboard.on("down", self.player.volume_down)
        self.keyboard.on("q", self.shutdown)
        self.keyboard.on("w", self._save_missed_clip)

    def _on_song_end(self):
        song = self.queue.next()
        if song:
            self.sm.transition(KaraokeState.IDLE)
            self.sm.transition(KaraokeState.PLAYING)
            self.player.play(song)
        else:
            self.sm.transition(KaraokeState.IDLE)
            self.player.show_idle_image()
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
        """Wait for recording to complete, then transcribe and act.

        Uses energy-based VAD: stop after 0.8s of silence once speech is detected.
        """
        max_frames = int(OUTPUT_RATE * 5 / FRAME_SIZE)
        silence_threshold = 300  # int16 amplitude
        silence_frames = 0
        silence_limit = int(OUTPUT_RATE * 0.8 / FRAME_SIZE)  # 0.8s of silence
        heard_speech = False
        last_count = 0

        while len(self._record_frames) < max_frames and self._recording:
            time.sleep(0.05)
            # Check new frames for silence detection
            current_count = len(self._record_frames)
            if current_count > last_count:
                for frame in self._record_frames[last_count:current_count]:
                    peak = int(np.max(np.abs(frame)))
                    if peak > silence_threshold:
                        heard_speech = True
                        silence_frames = 0
                    elif heard_speech:
                        silence_frames += 1
                last_count = current_count
                if heard_speech and silence_frames >= silence_limit:
                    break
        self._recording = False

        if not self._record_frames:
            self.sm.return_from_listening()
            return

        speak("Searching...")
        audio = np.concatenate(self._record_frames)
        text = transcribe_audio(audio, OUTPUT_RATE, self.config.whisper_model)
        if not text:
            self.sm.return_from_listening()
            return

        print(f"[voice] heard: {text}")
        intent, song = self._claude_parse(text)
        if intent == "unknown":
            # API failed, fall back to regex
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
                self.sm.return_from_listening(fire_callbacks=False)
                if self.sm.state == KaraokeState.PLAYING:
                    self.player.pause()
                    self.sm.transition(KaraokeState.PAUSED)
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
        elif intent == "joke":
            self._tell_joke()
        elif intent == "cancel":
            self.sm.return_from_listening()
        else:
            speak("Sorry, I didn't understand that")
            self.sm.return_from_listening()

    def _tell_joke(self):
        """Ask Claude for a joke and speak it."""
        self.sm.return_from_listening()
        try:
            import anthropic
            import random
            client = anthropic.Anthropic()
            categories = [
                "music", "singing", "karaoke", "animals", "food",
                "science", "technology", "sports", "movies", "puns",
            ]
            cat = random.choice(categories)
            msg = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=200,
                temperature=1.0,
                messages=[{
                    "role": "user",
                    "content": f"Tell a short, funny {cat} joke. Just the joke, nothing else. Keep it under 2 sentences."
                }],
            )
            joke = msg.content[0].text
        except Exception as e:
            print(f"[joke] Claude API error: {e}", flush=True)
            joke = "Why did the karaoke singer bring a ladder? To reach the high notes."
        speak(joke)

    def _claude_parse(self, text: str) -> tuple[str, str | None]:
        """Use Claude to interpret a voice command that regex couldn't parse."""
        try:
            import anthropic
            import json
            client = anthropic.Anthropic()
            msg = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": f"""Voice command from a karaoke machine user (may contain transcription errors):
"{text}"

Valid intents: play <song>, skip, pause, resume, queue, volume_up, volume_down, joke, cancel
Respond with JSON only: {{"intent": "...", "song": "..." or null}}
If it sounds like they want to play a song, extract the song name with correct spelling.""",
                }],
            )
            raw = msg.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)
            intent = parsed.get("intent", "unknown")
            song = parsed.get("song")
            print(f"[claude] corrected '{text}' -> intent={intent}, song={song}", flush=True)
            return (intent, song)
        except Exception as e:
            print(f"[claude] parse error: {e}", flush=True)
            return ("unknown", None)

    def _on_queue_song_added(self):
        """Fired by SongQueue when a song lands. Start playback immediately if
        we're idle. Replaces the old 60-second polling loop in
        _try_start_playback so songs that take longer than 60s to land in the
        queue (large download, Spleeter cold start, slow network) still play."""
        if self.sm.state != KaraokeState.IDLE:
            return
        song = self.queue.next()
        if song is None:
            return
        self.sm.transition(KaraokeState.PLAYING)
        self.player.play(song)

    def _try_start_playback(self):
        """Compatibility shim. The actual logic is now event-driven via the
        SongQueue.on_add callback wired in _setup_callbacks. We still try once
        immediately in case the song was already cached and added synchronously
        before the callback was registered (defense in depth)."""
        self._on_queue_song_added()

    def _save_clip(self, tag: str, extra_frames: list[np.ndarray] | None = None):
        """Save the rolling buffer (+ optional extra frames) as a WAV clip."""
        frames = list(self._clip_buffer)
        if extra_frames:
            frames.extend(extra_frames)
        if not frames:
            return
        os.makedirs(self.config.clips_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        path = os.path.join(self.config.clips_dir, f"{ts}_{tag}.wav")
        audio = np.concatenate(frames)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(OUTPUT_RATE)
            wf.writeframes(audio.tobytes())
        print(f"[clip] saved {path} ({len(audio) / OUTPUT_RATE:.1f}s)")

    def _save_missed_clip(self):
        """Keyboard shortcut handler: save current buffer as a missed wakeword clip."""
        self._save_clip("missed")

    def _on_wakeword_detected(self) -> threading.Thread:
        """Collect ~0.5s of post-detection audio and save a clip.

        Returns the save thread so callers (mainly tests) can join on it.
        """
        self.wakeword.reset()
        post_frames = []
        for _ in range(6):
            pf = self._audio.get_frame()
            if pf is None:
                break
            post_frames.append(pf)
        save_thread = threading.Thread(
            target=self._save_clip,
            args=("detected", post_frames),
            daemon=True,
        )
        save_thread.start()
        return save_thread

    def _mic_loop(self):
        """Read 16kHz frames from JACK engine for wakeword and command recording.

        The JackAudioEngine handles mic capture, monitoring, and reverb.
        This loop receives downsampled 16kHz int16 frames via get_frame().
        """
        print("Mic stream opened — listening for wakeword...")
        frame_count = 0
        wake_threshold = 500  # well above noise floor of 8-12
        last_wake = 0
        wake_cooldown = 30  # seconds between wake attempts
        while self._running:
            frame = self._audio.get_frame()
            if frame is None:
                break

            self._clip_buffer.append(frame)

            # Wake screen on mic noise (OLED burn-in protection)
            peak = int(np.max(np.abs(frame)))
            if peak > wake_threshold and self.player._screen_blanked:
                now = time.monotonic()
                if now - last_wake > wake_cooldown:
                    last_wake = now
                    self.player.wake_screen()
                    print(f"[screen] woke on mic noise (peak={peak})")

            if self._recording:
                self._record_frames.append(frame)
                continue

            if self.sm.state in (KaraokeState.IDLE, KaraokeState.PAUSED):
                if self.wakeword.process_frame(frame):
                    print("Wakeword detected!")
                    self._on_wakeword_detected()
                    self.sm.transition(KaraokeState.LISTENING)
                    self._listen_for_command()
                frame_count += 1
                if frame_count % 500 == 0:
                    print(f"[mic] frames={frame_count}, peak={peak}")

    def run(self):
        self._running = True
        os.makedirs(self.config.cache_dir, exist_ok=True)
        self._audio.start()
        set_audio_engine(self._audio)
        self.player.show_idle_image()
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
        self._audio.shutdown()
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
