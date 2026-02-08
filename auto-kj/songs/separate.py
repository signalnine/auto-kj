import os
import subprocess
from spleeter.separator import Separator

_separator = None


def _get_separator() -> Separator:
    global _separator
    if _separator is None:
        _separator = Separator("spleeter:2stems")
    return _separator


def _instrumental_path(output_dir: str) -> str:
    return os.path.join(output_dir, "accompaniment.wav")


def extract_audio(video_path: str, audio_path: str) -> str:
    """Extract audio from video file using ffmpeg."""
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vn", "-acodec", "pcm_s16le",
         "-ar", "44100", "-ac", "2", "-y", audio_path],
        check=True, capture_output=True,
    )
    return audio_path


def separate_vocals(video_path: str, output_dir: str) -> str:
    """Extract audio from video, then run Spleeter to separate vocals."""
    audio_path = os.path.join(output_dir, "audio.wav")
    extract_audio(video_path, audio_path)
    sep = _get_separator()
    sep.separate_to_file(audio_path, output_dir)
    # Clean up intermediate audio file
    if os.path.exists(audio_path):
        os.remove(audio_path)
    return _instrumental_path(output_dir)
