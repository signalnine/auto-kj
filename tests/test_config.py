import os
import pytest
from config import Config

def test_default_config():
    c = Config()
    assert c.cache_dir == os.path.expanduser("~/.auto-kj/cache")
    assert c.cache_max_bytes == 10 * 1024 * 1024 * 1024
    assert c.whisper_model == "small"
    assert c.clips_dir == os.path.expanduser("~/.auto-kj/clips")

def test_config_from_env(monkeypatch):
    monkeypatch.setenv("AUTOKJ_CACHE_DIR", "/tmp/kj-cache")
    monkeypatch.setenv("AUTOKJ_WHISPER_MODEL", "base")
    monkeypatch.setenv("AUTOKJ_CLIPS_DIR", "/tmp/kj-clips")
    c = Config()
    assert c.cache_dir == "/tmp/kj-cache"
    assert c.whisper_model == "base"
    assert c.clips_dir == "/tmp/kj-clips"
