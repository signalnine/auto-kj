import whisper
import numpy as np

_models: dict[str, object] = {}


def _get_model(model_name: str = "small"):
    if model_name not in _models:
        _models[model_name] = whisper.load_model(model_name)
    return _models[model_name]


def transcribe_audio(
    audio_data: np.ndarray,
    sample_rate: int = 16000,
    model_name: str = "small",
) -> str:
    model = _get_model(model_name)
    # Whisper expects float32 audio normalized to [-1, 1]
    if audio_data.dtype == np.int16:
        audio_data = audio_data.astype(np.float32) / 32768.0

    audio_data = whisper.pad_or_trim(audio_data)
    result = model.transcribe(audio_data, fp16=False)
    return result["text"].strip()
