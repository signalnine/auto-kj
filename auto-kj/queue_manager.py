import threading
from collections import deque
from typing import Callable


class SongQueue:
    def __init__(self):
        self._queue: deque[dict] = deque()
        self._lock = threading.Lock()
        self._on_add: Callable[[], None] | None = None

    def on_add(self, callback: Callable[[], None]):
        """Register a callback fired after each add(). Used so the playback
        controller can start a song the moment it lands in the queue rather
        than polling."""
        self._on_add = callback

    def add(self, song: dict):
        with self._lock:
            self._queue.append(song)
        cb = self._on_add
        if cb is not None:
            cb()

    def next(self) -> dict | None:
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def peek(self) -> dict | None:
        with self._lock:
            return self._queue[0] if self._queue else None

    def list(self) -> list[dict]:
        with self._lock:
            return list(self._queue)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._queue) == 0
