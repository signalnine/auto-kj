import os
import subprocess
import threading
import time

_MPV_SOCK = "/tmp/auto-kj-mpv.sock"


_IDLE_IMAGE = os.path.join(os.path.dirname(__file__), "auto-kj.png")


class Player:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._idle_proc: subprocess.Popen | None = None
        self._on_end_callback = None
        self._volume = 100
        self._paused = False
        self._lock = threading.Lock()

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

    def show_idle_image(self):
        """Display the idle hero image on screen via mpv."""
        with self._lock:
            if self._idle_proc and self._idle_proc.poll() is None:
                return
            if not os.path.exists(_IDLE_IMAGE):
                print(f"[player] idle image not found: {_IDLE_IMAGE}")
                return
            self._idle_proc = subprocess.Popen(
                [
                    "mpv",
                    "--vo=drm", "--drm-connector=auto",
                    "--image-display-duration=inf",
                    "--no-audio",
                    "--really-quiet",
                    _IDLE_IMAGE,
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print("[player] showing idle image")

    def hide_idle_image(self):
        """Stop displaying the idle hero image."""
        with self._lock:
            if self._idle_proc and self._idle_proc.poll() is None:
                self._idle_proc.terminate()
                try:
                    self._idle_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._idle_proc.kill()
                self._idle_proc = None

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
