import pyttsx3
import threading

_lock = threading.Lock()


def speak(text: str):
    def _speak():
        with _lock:
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
    threading.Thread(target=_speak, daemon=True).start()
