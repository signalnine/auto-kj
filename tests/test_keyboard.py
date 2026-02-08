import pytest
from unittest.mock import MagicMock
from keyboard import KeyboardHandler


def test_register_and_dispatch():
    handler = KeyboardHandler()
    callback = MagicMock()
    handler.on("space", callback)
    handler.dispatch("space")
    callback.assert_called_once()


def test_dispatch_unknown_key():
    handler = KeyboardHandler()
    # Should not raise
    handler.dispatch("unknown_key")


def test_multiple_handlers():
    handler = KeyboardHandler()
    cb1 = MagicMock()
    cb2 = MagicMock()
    handler.on("space", cb1)
    handler.on("escape", cb2)
    handler.dispatch("space")
    cb1.assert_called_once()
    cb2.assert_not_called()
