import os
import random
import subprocess
import tempfile
import threading
import time
from datetime import datetime

_MPV_SOCK = "/tmp/auto-kj-mpv.sock"


_IDLE_IMAGE = os.path.join(os.path.dirname(__file__), "auto-kj.png")
_REFRESH_VIDEO_CACHE = os.path.expanduser("~/.auto-kj/cache/pixel-refresh.mp4")

_SONG_SUGGESTIONS = [
    # Classic karaoke
    "Don't Stop Believin' by Journey",
    "Bohemian Rhapsody by Queen",
    "Sweet Caroline by Neil Diamond",
    "Living on a Prayer by Bon Jovi",
    "I Will Survive by Gloria Gaynor",
    "Total Eclipse of the Heart by Bonnie Tyler",
    "Take Me Home, Country Roads by John Denver",
    "Mr. Brightside by The Killers",
    "Summer Nights from Grease",
    "Wannabe by Spice Girls",
    "Dancing Queen by ABBA",
    "Under Pressure by Queen",
    "Tiny Dancer by Elton John",
    "You Oughta Know by Alanis Morissette",
    "I Want It That Way by Backstreet Boys",
    "Respect by Aretha Franklin",
    "Piano Man by Billy Joel",
    "Livin' La Vida Loca by Ricky Martin",
    "Baby One More Time by Britney Spears",
    "Since U Been Gone by Kelly Clarkson",
    "Somebody That I Used to Know by Gotye",
    "Hey Jude by The Beatles",
    "Billie Jean by Michael Jackson",
    "Girls Just Want to Have Fun by Cyndi Lauper",
    "Love Shack by The B-52's",
    "Build Me Up Buttercup by The Foundations",
    "Africa by Toto",
    "Wonderwall by Oasis",
    "Jessie's Girl by Rick Springfield",
    "Come On Eileen by Dexys Midnight Runners",
    "It's Raining Men by The Weather Girls",
    "Ice Ice Baby by Vanilla Ice",
    "Jolene by Dolly Parton",
    "Ring of Fire by Johnny Cash",
    "Crazy by Patsy Cline",
    "Stand By Me by Ben E. King",
    "Ain't No Mountain High Enough by Marvin Gaye",
    "Shallow by Lady Gaga",
    "Uptown Funk by Bruno Mars",
    "Rolling in the Deep by Adele",
    "Zombie by The Cranberries",
    "No Scrubs by TLC",
    "Toxic by Britney Spears",
    "Everywhere by Fleetwood Mac",
    "Take On Me by a-ha",
    # Disney
    "Let It Go from Frozen",
    "A Whole New World from Aladdin",
    "Under the Sea from The Little Mermaid",
    "Hakuna Matata from The Lion King",
    "Part of Your World from The Little Mermaid",
    "Be Our Guest from Beauty and the Beast",
    "How Far I'll Go from Moana",
    "You're Welcome from Moana",
    "We Don't Talk About Bruno from Encanto",
    "Into the Unknown from Frozen 2",
    "Supercalifragilisticexpialidocious from Mary Poppins",
    "Friend Like Me from Aladdin",
    "I Just Can't Wait to Be King from The Lion King",
    "Can You Feel the Love Tonight from The Lion King",
    "Colors of the Wind from Pocahontas",
    "You've Got a Friend in Me from Toy Story",
    "When You Wish Upon a Star from Pinocchio",
    "Circle of Life from The Lion King",
    "Reflection from Mulan",
    "Go the Distance from Hercules",
    "Beauty and the Beast from Beauty and the Beast",
    "Do You Want to Build a Snowman from Frozen",
    "Surface Pressure from Encanto",
    "Remember Me from Coco",
    "I See the Light from Tangled",
    "Almost There from The Princess and the Frog",
]


class Player:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._idle_proc: subprocess.Popen | None = None
        self._idle_cycle_stop: threading.Event | None = None
        self._on_end_callback = None
        self._volume = 100
        self._paused = False
        self._lock = threading.Lock()
        self._screen_blanked = False
        self._screen_blank_seconds = 600  # 10 minutes

    def on_song_end(self, callback):
        self._on_end_callback = callback

    def play(self, song: dict):
        self.hide_idle_image()
        print(f"[player] Playing: {song.get('title', 'unknown')} type={song.get('source_type')}")
        if song["source_type"] == "karaoke":
            path = song["video_path"]
        else:
            path = song.get("instrumental_path") or song.get("video_path")
        print(f"[player] Loading: {path}")
        self._start_mpv(path)

    def _is_overnight(self) -> bool:
        """Check if current time is in the overnight refresh window (2am-6am)."""
        hour = datetime.now().hour
        return 2 <= hour < 6

    def _get_refresh_video_path(self) -> str | None:
        """Get path to cached pixel-refresh video, downloading if needed."""
        if os.path.exists(_REFRESH_VIDEO_CACHE):
            return _REFRESH_VIDEO_CACHE
        try:
            os.makedirs(os.path.dirname(_REFRESH_VIDEO_CACHE), exist_ok=True)
            subprocess.run(
                [
                    "yt-dlp",
                    "-f", "bestvideo[height<=1080][ext=mp4]",
                    "--no-audio",
                    "-o", _REFRESH_VIDEO_CACHE,
                    "https://www.youtube.com/watch?v=mMDGLOOPOIs",
                ],
                capture_output=True, timeout=120,
            )
            if os.path.exists(_REFRESH_VIDEO_CACHE):
                print("[player] downloaded pixel-refresh video")
                return _REFRESH_VIDEO_CACHE
        except Exception as e:
            print(f"[player] failed to download pixel-refresh video: {e}")
        return None

    def _blank_screen(self):
        """Blank the screen by showing solid black via mpv (prevents TTY burn-in)."""
        self._kill_idle_proc()
        with self._lock:
            self._idle_proc = subprocess.Popen(
                [
                    "mpv",
                    "--vo=drm", "--drm-connector=auto",
                    "--image-display-duration=inf",
                    "--no-audio",
                    "--really-quiet",
                    "lavfi://[color=black:s=1920x1080:r=1]",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        self._screen_blanked = True
        print("[player] screen blanked (OLED protection)")

    def wake_screen(self):
        """Wake the screen from blank state by re-showing idle image."""
        if not self._screen_blanked:
            return
        self._screen_blanked = False
        self._show_idle_once()

    def show_idle_image(self):
        """Display the idle hero image on screen with a song suggestion.

        Blanks after _screen_blank_seconds to prevent OLED burn-in.
        Cycles to a new suggestion every hour.
        """
        self._stop_idle_cycle()
        self._screen_blanked = False
        self._show_idle_once()
        stop = threading.Event()
        self._idle_cycle_stop = stop
        blank_seconds = self._screen_blank_seconds
        def _cycle():
            # First wait: blank after timeout
            if not stop.wait(blank_seconds):
                self._blank_screen()
            # Then cycle hourly: show for blank_seconds, then blank again
            while not stop.wait(3600 - blank_seconds):
                self._show_idle_once()
                self._screen_blanked = False
                if not stop.wait(blank_seconds):
                    self._blank_screen()
        threading.Thread(target=_cycle, daemon=True).start()

    def _show_idle_once(self):
        with self._lock:
            if self._idle_proc and self._idle_proc.poll() is None:
                return
            if self._is_overnight():
                path = self._get_refresh_video_path()
                if path:
                    self._idle_proc = subprocess.Popen(
                        [
                            "mpv",
                            "--vo=drm", "--drm-connector=auto",
                            "--no-audio",
                            "--really-quiet",
                            "--loop",
                            path,
                        ],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    print("[player] playing overnight pixel-refresh video")
                    return
            if not os.path.exists(_IDLE_IMAGE):
                print(f"[player] idle image not found: {_IDLE_IMAGE}")
                return
            song = random.choice(_SONG_SUGGESTIONS)
            sub_path = self._write_idle_subtitle(song)
            self._idle_proc = subprocess.Popen(
                [
                    "mpv",
                    "--vo=drm", "--drm-connector=auto",
                    "--image-display-duration=inf",
                    "--no-audio",
                    "--really-quiet",
                    f"--sub-file={sub_path}",
                    _IDLE_IMAGE,
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print(f"[player] showing idle image (try: {song})")

    @staticmethod
    def _write_idle_subtitle(song: str) -> str:
        """Write an ASS subtitle file with the song suggestion."""
        ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,9:00:00.00,Default,,0,0,0,,Try saying\\N{{\\fs56\\i1}}"Hey Karaoke play {song}"
"""
        fd, path = tempfile.mkstemp(suffix=".ass", prefix="auto-kj-idle-")
        with os.fdopen(fd, "w") as f:
            f.write(ass_content)
        return path

    def _stop_idle_cycle(self):
        if self._idle_cycle_stop:
            self._idle_cycle_stop.set()
            self._idle_cycle_stop = None

    def _kill_idle_proc(self):
        with self._lock:
            if self._idle_proc and self._idle_proc.poll() is None:
                self._idle_proc.terminate()
                try:
                    self._idle_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._idle_proc.kill()
                self._idle_proc = None

    def hide_idle_image(self):
        """Stop displaying the idle hero image."""
        self._stop_idle_cycle()
        self._kill_idle_proc()
        self._screen_blanked = False

    def _start_mpv(self, path: str):
        with self._lock:
            self.stop()
            self._paused = False
            try:
                os.unlink(_MPV_SOCK)
            except FileNotFoundError:
                pass
            self._proc = subprocess.Popen(
                [
                    "mpv",
                    "--vo=drm", "--drm-connector=auto",
                    "--ao=jack",
                    f"--volume={self._volume}",
                    f"--input-ipc-server={_MPV_SOCK}",
                    path,
                ],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        threading.Thread(target=self._wait_for_end, daemon=True).start()

    def _wait_for_end(self):
        proc = self._proc
        if proc is None:
            return
        proc.wait()
        output = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
        print(f"[player] mpv exited with code {proc.returncode}")
        if output.strip():
            for line in output.strip().split("\n"):
                print(f"[player] {line.strip()}")
        with self._lock:
            if self._proc is proc:
                self._proc = None
        if self._on_end_callback:
            self._on_end_callback()

    def _send_command(self, *args):
        """Send command to mpv via IPC socket."""
        import json
        import socket
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(_MPV_SOCK)
            cmd = json.dumps({"command": list(args)}) + "\n"
            sock.sendall(cmd.encode())
            sock.close()
        except Exception:
            pass

    def pause(self):
        self._paused = True
        self._send_command("set_property", "pause", True)

    def resume(self):
        self._paused = False
        self._send_command("set_property", "pause", False)

    def skip(self):
        self.stop()

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def volume_up(self, step: int = 10):
        self._volume = min(150, self._volume + step)
        self._send_command("set_property", "volume", self._volume)

    def volume_down(self, step: int = 10):
        self._volume = max(0, self._volume - step)
        self._send_command("set_property", "volume", self._volume)

    @property
    def is_playing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def shutdown(self):
        self.stop()
        self.hide_idle_image()
