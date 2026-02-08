import pytest
from unittest.mock import patch, MagicMock
from songs.separate import separate_vocals, extract_audio


@patch("songs.separate.subprocess.run")
def test_extract_audio(mock_run, tmp_path):
    video = str(tmp_path / "video.mp4")
    audio = str(tmp_path / "audio.wav")
    mock_run.return_value = MagicMock(returncode=0)
    result = extract_audio(video, audio)
    assert result == audio
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "ffmpeg" in args
    assert video in args
    assert audio in args


@patch("songs.separate.Separator")
@patch("songs.separate.extract_audio")
def test_separate_vocals(mock_extract, mock_sep_cls, tmp_path):
    mock_sep = MagicMock()
    mock_sep_cls.return_value = mock_sep
    mock_extract.return_value = str(tmp_path / "audio.wav")

    video_path = str(tmp_path / "video.mp4")
    output_dir = str(tmp_path / "output")

    result = separate_vocals(video_path, output_dir)
    mock_extract.assert_called_once()
    mock_sep.separate_to_file.assert_called_once()
    assert result.endswith("accompaniment.wav")


def test_instrumental_path():
    from songs.separate import _instrumental_path
    assert _instrumental_path("/cache/abc123") == "/cache/abc123/accompaniment.wav"
