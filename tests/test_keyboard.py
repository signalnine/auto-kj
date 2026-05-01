import pytest
from unittest.mock import MagicMock, patch
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


def test_find_keyboard_closes_non_matching_devices():
    import keyboard as kb_mod

    fake_ecodes = MagicMock()
    fake_ecodes.EV_KEY = 1
    fake_ecodes.KEY_SPACE = 57
    fake_ecodes.KEY_ESC = 1

    mouse_dev = MagicMock()
    mouse_dev.capabilities.return_value = {2: [0x110]}
    kbd_dev = MagicMock()
    kbd_dev.capabilities.return_value = {1: [57, 1]}
    extra_dev = MagicMock()
    extra_dev.capabilities.return_value = {2: [0x111]}

    devices = [mouse_dev, kbd_dev, extra_dev]

    def fake_input_device(path):
        return devices[int(path)]

    with patch.object(kb_mod, "list_devices", return_value=["0", "1", "2"]), \
         patch.object(kb_mod, "InputDevice", side_effect=fake_input_device), \
         patch.object(kb_mod, "ecodes", fake_ecodes), \
         patch.object(kb_mod, "HAS_EVDEV", True):
        handler = KeyboardHandler()
        result = handler._find_keyboard()

    assert result == "1"
    mouse_dev.close.assert_called_once()
    kbd_dev.close.assert_called_once()
    extra_dev.capabilities.assert_not_called()


def test_find_keyboard_closes_all_when_no_match():
    import keyboard as kb_mod

    fake_ecodes = MagicMock()
    fake_ecodes.EV_KEY = 1
    fake_ecodes.KEY_SPACE = 57
    fake_ecodes.KEY_ESC = 1

    dev_a = MagicMock()
    dev_a.capabilities.return_value = {2: [0x110]}
    dev_b = MagicMock()
    dev_b.capabilities.return_value = {1: [99]}

    devices = [dev_a, dev_b]

    def fake_input_device(path):
        return devices[int(path)]

    with patch.object(kb_mod, "list_devices", return_value=["0", "1"]), \
         patch.object(kb_mod, "InputDevice", side_effect=fake_input_device), \
         patch.object(kb_mod, "ecodes", fake_ecodes), \
         patch.object(kb_mod, "HAS_EVDEV", True):
        handler = KeyboardHandler()
        result = handler._find_keyboard()

    assert result is None
    dev_a.close.assert_called_once()
    dev_b.close.assert_called_once()
