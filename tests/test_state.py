import pytest
from state import KaraokeState, StateMachine


def test_initial_state():
    sm = StateMachine()
    assert sm.state == KaraokeState.IDLE


def test_idle_to_playing():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    assert sm.state == KaraokeState.PLAYING


def test_playing_to_paused():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    sm.transition(KaraokeState.PAUSED)
    assert sm.state == KaraokeState.PAUSED


def test_playing_to_listening():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    sm.transition(KaraokeState.LISTENING)
    assert sm.state == KaraokeState.LISTENING


def test_paused_to_playing():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    sm.transition(KaraokeState.PAUSED)
    sm.transition(KaraokeState.PLAYING)
    assert sm.state == KaraokeState.PLAYING


def test_listening_returns_to_previous():
    sm = StateMachine()
    sm.transition(KaraokeState.PLAYING)
    sm.transition(KaraokeState.LISTENING)
    sm.return_from_listening()
    assert sm.state == KaraokeState.PLAYING


def test_on_enter_callback():
    sm = StateMachine()
    entered = []
    sm.on_enter(KaraokeState.PLAYING, lambda: entered.append(True))
    sm.transition(KaraokeState.PLAYING)
    assert entered == [True]


def test_return_from_listening_fires_on_enter_callback():
    """return_from_listening should fire on_enter callbacks for the restored state."""
    sm = StateMachine()
    entered = []
    sm.on_enter(KaraokeState.PLAYING, lambda: entered.append("playing"))
    sm.transition(KaraokeState.PLAYING)
    entered.clear()  # ignore the initial transition's callback
    sm.transition(KaraokeState.LISTENING)
    sm.return_from_listening()
    assert entered == ["playing"]


def test_return_from_listening_suppresses_callbacks_when_requested():
    """return_from_listening(fire_callbacks=False) should skip callbacks."""
    sm = StateMachine()
    entered = []
    sm.on_enter(KaraokeState.PLAYING, lambda: entered.append("playing"))
    sm.transition(KaraokeState.PLAYING)
    entered.clear()
    sm.transition(KaraokeState.LISTENING)
    sm.return_from_listening(fire_callbacks=False)
    assert entered == []
    assert sm.state == KaraokeState.PLAYING


def test_return_from_listening_noop_when_not_listening():
    """return_from_listening is a no-op and fires no callbacks when not in LISTENING."""
    sm = StateMachine()
    entered = []
    sm.on_enter(KaraokeState.IDLE, lambda: entered.append("idle"))
    sm.return_from_listening()
    assert entered == []
    assert sm.state == KaraokeState.IDLE
