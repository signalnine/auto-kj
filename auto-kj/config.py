import os
from dataclasses import dataclass, field

@dataclass
class Config:
    cache_dir: str = field(default=None)
    cache_max_bytes: int = 10 * 1024 * 1024 * 1024
    whisper_model: str = field(default=None)
    wakeword_model: str = field(default=None)

    def __post_init__(self):
        if self.cache_dir is None:
            self.cache_dir = os.environ.get("AUTOKJ_CACHE_DIR", os.path.expanduser("~/.auto-kj/cache"))
        if self.whisper_model is None:
            self.whisper_model = os.environ.get("AUTOKJ_WHISPER_MODEL", "small")
        if self.wakeword_model is None:
            self.wakeword_model = os.environ.get("AUTOKJ_WAKEWORD_MODEL", "hey_jarvis")
