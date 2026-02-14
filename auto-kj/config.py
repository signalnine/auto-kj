import os
from dataclasses import dataclass, field

@dataclass
class Config:
    cache_dir: str = field(default=None)
    cache_max_bytes: int = 10 * 1024 * 1024 * 1024
    whisper_model: str = field(default=None)
    wakeword_model: str = field(default=None)
    # JACK audio settings
    jack_device: str = field(default=None)
    jack_mic_device: str = field(default=None)
    jack_period: int = field(default=None)
    clips_dir: str = field(default=None)

    def __post_init__(self):
        if self.cache_dir is None:
            self.cache_dir = os.environ.get("AUTOKJ_CACHE_DIR", os.path.expanduser("~/.auto-kj/cache"))
        if self.whisper_model is None:
            self.whisper_model = os.environ.get("AUTOKJ_WHISPER_MODEL", "small")
        if self.wakeword_model is None:
            self.wakeword_model = os.environ.get("AUTOKJ_WAKEWORD_MODEL",
                os.path.expanduser("~/.auto-kj/models/hey_karaoke.onnx"))
        if self.jack_device is None:
            self.jack_device = os.environ.get("AUTOKJ_JACK_DEVICE", "hw:1,0")
        if self.jack_mic_device is None:
            self.jack_mic_device = os.environ.get("AUTOKJ_JACK_MIC_DEVICE", "hw:2")
        if self.jack_period is None:
            self.jack_period = int(os.environ.get("AUTOKJ_JACK_PERIOD", "256"))
        if self.clips_dir is None:
            self.clips_dir = os.environ.get("AUTOKJ_CLIPS_DIR", os.path.expanduser("~/.auto-kj/clips"))
