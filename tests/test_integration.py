"""Integration tests using mocks for external services."""
import os
import pytest
from unittest.mock import patch, MagicMock
from config import Config
from state import KaraokeState, StateMachine
from queue_manager import SongQueue
from songs.pipeline import SongPipeline
from voice.commands import parse_command


def test_full_voice_command_flow():
    """Simulate: user says 'play Bohemian Rhapsody' -> parse -> intent."""
    text = "play Bohemian Rhapsody"
    intent, song = parse_command(text)
    assert intent == "play"
    assert song == "Bohemian Rhapsody"


def test_state_machine_full_cycle():
    sm = StateMachine()
    assert sm.state == KaraokeState.IDLE

    sm.transition(KaraokeState.PLAYING)
    assert sm.state == KaraokeState.PLAYING

    sm.transition(KaraokeState.LISTENING)
    assert sm.state == KaraokeState.LISTENING

    sm.return_from_listening()
    assert sm.state == KaraokeState.PLAYING

    sm.transition(KaraokeState.PAUSED)
    assert sm.state == KaraokeState.PAUSED

    sm.transition(KaraokeState.PLAYING)
    assert sm.state == KaraokeState.PLAYING

    sm.transition(KaraokeState.IDLE)
    assert sm.state == KaraokeState.IDLE


def test_queue_through_pipeline():
    cache = MagicMock()
    cache.search.return_value = [
        {
            "youtube_id": "abc",
            "title": "Bohemian Rhapsody",
            "source_type": "karaoke",
            "video_path": "abc/video.mp4",
            "instrumental_path": None,
            "lyrics_path": None,
        }
    ]
    queue = SongQueue()
    pipeline = SongPipeline(cache, queue, MagicMock(), "/tmp/cache")
    pipeline.request("Bohemian Rhapsody")
    assert not queue.is_empty()
    song = queue.next()
    assert song["title"] == "Bohemian Rhapsody"
