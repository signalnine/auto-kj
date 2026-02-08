import threading
from collections import deque


class SongQueue:
    def __init__(self):
        self._queue: deque[dict] = deque()
        self._lock = threading.Lock()

    def add(self, song: dict):
        with self._lock:
            self._queue.append(song)

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
