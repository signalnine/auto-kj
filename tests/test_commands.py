import pytest
from voice.commands import parse_command


def test_play_command():
    intent, song = parse_command("play Bohemian Rhapsody")
    assert intent == "play"
    assert song == "Bohemian Rhapsody"


def test_play_with_by():
    intent, song = parse_command("play Yesterday by The Beatles")
    assert intent == "play"
    assert song == "Yesterday by The Beatles"


def test_sing_command():
    intent, song = parse_command("sing Don't Stop Believin")
    assert intent == "play"
    assert song == "Don't Stop Believin"


def test_add_command():
    intent, song = parse_command("add Wonderwall to the queue")
    assert intent == "play"
    assert "Wonderwall" in song


def test_skip():
    intent, song = parse_command("skip")
    assert intent == "skip"
    assert song is None


def test_next_song():
    intent, song = parse_command("next song")
    assert intent == "skip"


def test_pause():
    intent, song = parse_command("pause")
    assert intent == "pause"


def test_stop():
    intent, song = parse_command("stop")
    assert intent == "pause"


def test_resume():
    intent, song = parse_command("resume")
    assert intent == "resume"


def test_continue():
    intent, song = parse_command("continue")
    assert intent == "resume"


def test_queue():
    intent, song = parse_command("what's next")
    assert intent == "queue"


def test_show_queue():
    intent, song = parse_command("show queue")
    assert intent == "queue"


def test_volume_up():
    intent, song = parse_command("volume up")
    assert intent == "volume_up"


def test_louder():
    intent, song = parse_command("louder")
    assert intent == "volume_up"


def test_volume_down():
    intent, song = parse_command("volume down")
    assert intent == "volume_down"


def test_quieter():
    intent, song = parse_command("quieter")
    assert intent == "volume_down"


def test_cancel():
    intent, song = parse_command("cancel")
    assert intent == "cancel"


def test_never_mind():
    intent, song = parse_command("never mind")
    assert intent == "cancel"


def test_unknown():
    intent, song = parse_command("what is the meaning of life")
    assert intent == "unknown"
