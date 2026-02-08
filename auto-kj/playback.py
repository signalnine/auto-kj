import mpv
import threading


class Player:
    def __init__(self):
        self._mpv = mpv.MPV(
            input_default_bindings=False,
            input_vo_keyboard=False,
            fullscreen=True,
            vid="auto",
        )
        self._on_end_callback = None
        self._mpv.observe_property("idle-active", self._on_idle)

    def _on_idle(self, name, value):
        if value and self._on_end_callback:
            self._on_end_callback()

    def on_song_end(self, callback):
        self._on_end_callback = callback

    def play(self, song: dict):
        if song["source_type"] == "karaoke":
            self._mpv.loadfile(song["video_path"])
        else:
            path = song.get("instrumental_path") or song.get("video_path")
            self._mpv.loadfile(path)
            lyrics = song.get("lyrics_path")
            if lyrics:
                def add_subs():
                    import time
                    time.sleep(0.5)
                    try:
                        self._mpv.sub_add(lyrics)
                    except Exception:
                        pass
                threading.Thread(target=add_subs, daemon=True).start()

    def pause(self):
        self._mpv.pause = True

    def resume(self):
        self._mpv.pause = False

    def skip(self):
        self._mpv.stop()

    def volume_up(self, step: int = 10):
        self._mpv.volume = min(150, self._mpv.volume + step)

    def volume_down(self, step: int = 10):
        self._mpv.volume = max(0, self._mpv.volume - step)

    @property
    def is_playing(self) -> bool:
        return not self._mpv.idle_active

    def shutdown(self):
        self._mpv.terminate()
