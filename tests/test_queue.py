import pytest
from queue_manager import SongQueue


def test_enqueue_and_next():
    q = SongQueue()
    q.add({"youtube_id": "a", "title": "Song A"})
    q.add({"youtube_id": "b", "title": "Song B"})
    assert q.next()["youtube_id"] == "a"
    assert q.next()["youtube_id"] == "b"
    assert q.next() is None


def test_peek():
    q = SongQueue()
    q.add({"youtube_id": "a", "title": "Song A"})
    assert q.peek()["youtube_id"] == "a"
    assert q.peek()["youtube_id"] == "a"  # doesn't consume


def test_list():
    q = SongQueue()
    q.add({"youtube_id": "a", "title": "Song A"})
    q.add({"youtube_id": "b", "title": "Song B"})
    titles = [s["title"] for s in q.list()]
    assert titles == ["Song A", "Song B"]


def test_empty():
    q = SongQueue()
    assert q.is_empty()
    q.add({"youtube_id": "a", "title": "Song A"})
    assert not q.is_empty()


def test_skip():
    q = SongQueue()
    q.add({"youtube_id": "a", "title": "Song A"})
    q.add({"youtube_id": "b", "title": "Song B"})
    q.next()  # consume a
    assert q.next()["youtube_id"] == "b"


def test_on_add_callback_fires():
    """Registering an on_add callback lets the playback controller learn the
    moment a song lands rather than polling. Bug auto-kj-nez."""
    q = SongQueue()
    calls = []
    q.on_add(lambda: calls.append(1))
    q.add({"youtube_id": "a", "title": "Song A"})
    q.add({"youtube_id": "b", "title": "Song B"})
    assert calls == [1, 1]


def test_on_add_called_after_song_visible():
    """on_add must fire after the song has been appended, so the callback can
    safely call next()/peek()."""
    q = SongQueue()
    seen = []
    def cb():
        seen.append(q.peek())
    q.on_add(cb)
    q.add({"youtube_id": "a", "title": "Song A"})
    assert seen == [{"youtube_id": "a", "title": "Song A"}]
