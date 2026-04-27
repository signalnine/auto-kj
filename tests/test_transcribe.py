from unittest.mock import patch, MagicMock
import numpy as np

import voice.transcribe as transcribe_mod


def _reset():
    transcribe_mod._model = None
    if hasattr(transcribe_mod, "_models"):
        transcribe_mod._models.clear()


def test_first_call_loads_named_model():
    _reset()
    with patch("voice.transcribe.whisper") as whisper_mock:
        sentinel = MagicMock(name="small_model")
        whisper_mock.load_model.return_value = sentinel
        m = transcribe_mod._get_model("small")
        assert m is sentinel
        whisper_mock.load_model.assert_called_once_with("small")


def test_repeated_same_name_does_not_reload():
    _reset()
    with patch("voice.transcribe.whisper") as whisper_mock:
        whisper_mock.load_model.return_value = MagicMock()
        transcribe_mod._get_model("small")
        transcribe_mod._get_model("small")
        assert whisper_mock.load_model.call_count == 1


def test_different_name_reloads_with_new_name():
    _reset()
    with patch("voice.transcribe.whisper") as whisper_mock:
        small = MagicMock(name="small")
        medium = MagicMock(name="medium")
        whisper_mock.load_model.side_effect = lambda name: (
            small if name == "small" else medium
        )
        first = transcribe_mod._get_model("small")
        second = transcribe_mod._get_model("medium")
        assert first is small
        assert second is medium
        names_called = [c.args[0] for c in whisper_mock.load_model.call_args_list]
        assert names_called == ["small", "medium"]


def test_alternating_names_cache_per_name():
    _reset()
    with patch("voice.transcribe.whisper") as whisper_mock:
        whisper_mock.load_model.side_effect = lambda name: MagicMock(name=name)
        transcribe_mod._get_model("small")
        transcribe_mod._get_model("medium")
        transcribe_mod._get_model("small")
        transcribe_mod._get_model("medium")
        assert whisper_mock.load_model.call_count == 2


def test_transcribe_audio_uses_requested_model():
    _reset()
    with patch("voice.transcribe.whisper") as whisper_mock:
        small = MagicMock(name="small")
        medium = MagicMock(name="medium")
        small.transcribe.return_value = {"text": " hi small "}
        medium.transcribe.return_value = {"text": " hi medium "}
        whisper_mock.load_model.side_effect = lambda name: (
            small if name == "small" else medium
        )
        whisper_mock.pad_or_trim.side_effect = lambda x: x
        audio = np.zeros(16000, dtype=np.float32)
        out_small = transcribe_mod.transcribe_audio(audio, model_name="small")
        out_medium = transcribe_mod.transcribe_audio(audio, model_name="medium")
        assert out_small == "hi small"
        assert out_medium == "hi medium"
