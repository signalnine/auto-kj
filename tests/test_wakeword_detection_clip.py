"""Regression test for auto-kj-kj7:
post-wakeword frames must not be duplicated in the saved 'detected' clip."""
import collections
import wave
import numpy as np
from unittest.mock import MagicMock, patch

from config import Config


def test_wakeword_detection_saved_clip_has_no_duplicate_frames(tmp_path):
    """When wakeword fires, the saved clip contains pre-buffer frames plus
    each post-detection frame exactly once -- never twice."""
    from main import Karaoke

    with patch.object(Karaoke, "__init__", lambda self, *a, **kw: None):
        k = Karaoke.__new__(Karaoke)
    k.config = Config(clips_dir=str(tmp_path))
    k._clip_buffer = collections.deque(maxlen=25)
    k.wakeword = MagicMock()

    pre_frames = [np.full(1280, (i + 1) * 10, dtype=np.int16) for i in range(3)]
    for f in pre_frames:
        k._clip_buffer.append(f)

    post_frames = [np.full(1280, (i + 1) * 100, dtype=np.int16) for i in range(6)]
    k._audio = MagicMock()
    k._audio.get_frame.side_effect = post_frames + [None]

    import main as main_mod
    original_rate = main_mod.OUTPUT_RATE
    main_mod.OUTPUT_RATE = 16000
    try:
        save_thread = k._on_wakeword_detected()
        save_thread.join(timeout=5)
    finally:
        main_mod.OUTPUT_RATE = original_rate

    files = list(tmp_path.glob("*_detected.wav"))
    assert len(files) == 1, f"Expected exactly one detected clip, got {len(files)}"

    with wave.open(str(files[0]), "rb") as wf:
        got = wf.getnframes()
        samples = np.frombuffer(wf.readframes(got), dtype=np.int16)

    expected_frames = (len(pre_frames) + len(post_frames)) * 1280
    assert got == expected_frames, (
        f"Saved clip has {got} samples; expected {expected_frames} "
        f"(pre={len(pre_frames)} frames + post={len(post_frames)} frames). "
        f"A clip of {expected_frames + len(post_frames) * 1280} samples means "
        f"post frames were duplicated."
    )

    pre_samples = 3 * 1280
    np.testing.assert_array_equal(
        samples[:pre_samples],
        np.concatenate(pre_frames),
        err_msg="Pre-detection frames not preserved at start of clip",
    )
    np.testing.assert_array_equal(
        samples[pre_samples:],
        np.concatenate(post_frames),
        err_msg="Post-detection frames not appended after pre frames",
    )
