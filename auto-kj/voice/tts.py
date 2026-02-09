import pyttsx3
import threading
import queue

_queue: queue.Queue[str | None] = queue.Queue()
_started = False
_start_lock = threading.Lock()


def _worker():
    engine = pyttsx3.init()
    while True:
        text = _queue.get()
        if text is None:
            break
        engine.say(text)
        engine.runAndWait()


def speak(text: str):
    global _started
    with _start_lock:
        if not _started:
            threading.Thread(target=_worker, daemon=True).start()
            _started = True
    _queue.put(text)
