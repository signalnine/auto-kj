"""Tests for Karaoke._handle_intent state management."""
from unittest.mock import MagicMock, patch
import pytest

from state import KaraokeState


@pytest.fixture
def karaoke():
    """Build a Karaoke instance with mocked external deps."""
    with patch("main.Player"), patch("main.SongCache"), \
         patch("main.SongPipeline"), patch("main.WakeWordListener"), \
         patch("main.KeyboardHandler"), patch("main.JackAudioEngine"):
        from main import Karaoke
        from config import Config
        kj = Karaoke(Config())
        return kj


def _enter_listening_from(kj, origin: KaraokeState):
    """Put the state machine in LISTENING with the given previous state."""
    if origin == KaraokeState.PLAYING:
        kj.sm.transition(KaraokeState.PLAYING)
    elif origin == KaraokeState.PAUSED:
        kj.sm.transition(KaraokeState.PLAYING)
        kj.sm.transition(KaraokeState.PAUSED)
    # origin == IDLE: already IDLE on fresh StateMachine
    kj.sm.transition(KaraokeState.LISTENING)


def test_pause_from_playing_ends_in_paused(karaoke):
    """Spacebar pauses player and enters LISTENING. Voice 'pause' must
    leave state as PAUSED so wakeword can reactivate without spacebar."""
    _enter_listening_from(karaoke, KaraokeState.PLAYING)
    karaoke._handle_intent("pause", None)
    assert karaoke.sm.state == KaraokeState.PAUSED


def test_pause_from_paused_stays_paused(karaoke):
    """Wakeword from PAUSED -> LISTENING. 'pause' keeps state as PAUSED."""
    _enter_listening_from(karaoke, KaraokeState.PAUSED)
    karaoke._handle_intent("pause", None)
    assert karaoke.sm.state == KaraokeState.PAUSED


def test_pause_from_idle_stays_idle(karaoke):
    """Wakeword from IDLE -> LISTENING. 'pause' is a no-op, state stays IDLE."""
    _enter_listening_from(karaoke, KaraokeState.IDLE)
    karaoke._handle_intent("pause", None)
    assert karaoke.sm.state == KaraokeState.IDLE


def test_resume_from_playing_stays_playing(karaoke):
    """Sanity: 'resume' from LISTENING (prev=PLAYING) ends in PLAYING."""
    _enter_listening_from(karaoke, KaraokeState.PLAYING)
    karaoke._handle_intent("resume", None)
    assert karaoke.sm.state == KaraokeState.PLAYING


def test_resume_from_paused_ends_in_playing(karaoke):
    """'resume' from LISTENING (prev=PAUSED) ends in PLAYING."""
    _enter_listening_from(karaoke, KaraokeState.PAUSED)
    karaoke._handle_intent("resume", None)
    assert karaoke.sm.state == KaraokeState.PLAYING


@pytest.mark.parametrize("intent", [
    "volume_up", "volume_down", "queue", "cancel", "joke", "unknown",
])
def test_nonpause_intent_resumes_player_when_returning_to_playing(karaoke, intent):
    """Non-pause voice intents from LISTENING(prev=PLAYING) must resume the mpv
    player; spacebar paused mpv on entry so mic could hear the command."""
    _enter_listening_from(karaoke, KaraokeState.PLAYING)
    karaoke.player.resume.reset_mock()
    karaoke._handle_intent(intent, None)
    assert karaoke.sm.state == KaraokeState.PLAYING
    assert karaoke.player.resume.called, (
        f"player.resume was not called after intent={intent!r}"
    )


def test_pause_intent_does_not_resume_player(karaoke):
    """The 'pause' intent must leave mpv paused (no resume-then-repause blip)."""
    _enter_listening_from(karaoke, KaraokeState.PLAYING)
    karaoke.player.resume.reset_mock()
    karaoke._handle_intent("pause", None)
    assert karaoke.sm.state == KaraokeState.PAUSED
    assert not karaoke.player.resume.called, (
        "player.resume should not be called for 'pause' intent"
    )
