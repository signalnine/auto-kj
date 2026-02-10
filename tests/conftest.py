import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'auto-kj'))

# Mock optional dependencies that may not be installed in test environment
for mod_name in [
    "spleeter", "spleeter.separator",
    "evdev",
    "mpv",
    "pyttsx3",
    "openwakeword", "openwakeword.model",
    "whisper",
    "pyaudio",
    "jack",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
