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
