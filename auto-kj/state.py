import enum
import threading


class KaraokeState(enum.Enum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    LISTENING = "listening"


VALID_TRANSITIONS = {
    KaraokeState.IDLE: {KaraokeState.PLAYING, KaraokeState.LISTENING},
    KaraokeState.PLAYING: {KaraokeState.IDLE, KaraokeState.PAUSED, KaraokeState.LISTENING},
    KaraokeState.PAUSED: {KaraokeState.PLAYING, KaraokeState.IDLE, KaraokeState.LISTENING},
    KaraokeState.LISTENING: {KaraokeState.IDLE, KaraokeState.PLAYING, KaraokeState.PAUSED},
}


class StateMachine:
    def __init__(self):
        self.state = KaraokeState.IDLE
        self._previous = KaraokeState.IDLE
        self._callbacks: dict[KaraokeState, list[callable]] = {}
        self._lock = threading.Lock()

    def transition(self, new_state: KaraokeState):
        with self._lock:
            if new_state not in VALID_TRANSITIONS.get(self.state, set()):
                raise ValueError(f"Invalid transition: {self.state} -> {new_state}")
            if new_state == KaraokeState.LISTENING:
                self._previous = self.state
            self.state = new_state
        for cb in self._callbacks.get(new_state, []):
            cb()

    def return_from_listening(self):
        with self._lock:
            if self.state != KaraokeState.LISTENING:
                return
            self.state = self._previous

    def on_enter(self, state: KaraokeState, callback: callable):
        self._callbacks.setdefault(state, []).append(callback)
