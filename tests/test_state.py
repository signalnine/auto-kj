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
