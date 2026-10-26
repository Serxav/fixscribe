"""Ingest stage tests: tiny clips are built with ffmpeg, no fixtures committed."""

import json
import shutil
import subprocess
import wave

import pytest

from app.config import Settings
from app.pipeline import ingest
from app.pipeline.ingest import IngestError

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def make_settings(tmp_path, max_video_seconds=600):
    return Settings(model_api_key="", data_dir=tmp_path, max_video_seconds=max_video_seconds)


def make_clip(dst, size, duration=2, with_audio=True):
    """Build a tiny synthetic clip with ffmpeg (2 seconds)."""
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={size}:rate=30",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440"]
    cmd += ["-t", str(duration), "-c:v", "libx264", "-preset", "veryfast"]
    cmd += ["-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += [str(dst)]
    subprocess.run(cmd, check=True)


def read_wav_info(path):
    with wave.open(str(path), "rb") as wav:
        return wav.getnchannels(), wav.getframerate(), wav.getsampwidth()


def test_landscape_with_audio(tmp_path):
    make_clip(tmp_path / "original.mp4", "1920x1080")
    info = ingest.run(tmp_path, make_settings(tmp_path))
    assert (info.width, info.height) == (1280, 720)
    assert info.has_audio
    assert info.duration_s == pytest.approx(2, abs=0.2)
    assert read_wav_info(tmp_path / "audio.wav") == (1, 24000, 2)
    saved = json.loads((tmp_path / "ingest.json").read_text(encoding="utf-8"))
    assert saved == {
        "duration_s": info.duration_s,
        "width": 1280,
        "height": 720,
        "has_audio": True,
    }


def test_portrait_scales_to_720_wide(tmp_path):
    make_clip(tmp_path / "original.mp4", "1080x1920", with_audio=False)
    info = ingest.run(tmp_path, make_settings(tmp_path))
    assert (info.width, info.height) == (720, 1280)


def test_small_video_is_not_upscaled(tmp_path):
    make_clip(tmp_path / "original.mp4", "640x360", with_audio=False)
    info = ingest.run(tmp_path, make_settings(tmp_path))
    assert (info.width, info.height) == (640, 360)


def test_video_without_audio_has_no_wav(tmp_path):
    make_clip(tmp_path / "original.mp4", "640x360", with_audio=False)
    info = ingest.run(tmp_path, make_settings(tmp_path))
    assert not info.has_audio
    assert not (tmp_path / "audio.wav").exists()
    saved = json.loads((tmp_path / "ingest.json").read_text(encoding="utf-8"))
    assert saved["has_audio"] is False


def test_mov_input_works(tmp_path):
    make_clip(tmp_path / "original.mov", "1920x1080")
    info = ingest.run(tmp_path, make_settings(tmp_path))
    assert (info.width, info.height) == (1280, 720)
    assert (tmp_path / "video.mp4").exists()


def test_too_long_video_is_rejected_before_converting(tmp_path):
    make_clip(tmp_path / "original.mp4", "640x360", with_audio=False)
    with pytest.raises(IngestError, match="too long"):
        ingest.run(tmp_path, make_settings(tmp_path, max_video_seconds=1))
    assert not (tmp_path / "video.mp4").exists()


def test_text_file_is_not_a_readable_video(tmp_path):
    (tmp_path / "original.mp4").write_text("not a video", encoding="utf-8")
    with pytest.raises(IngestError, match="not a readable video"):
        ingest.run(tmp_path, make_settings(tmp_path))
    assert list(tmp_path.glob("*.tmp.*")) == []


def test_missing_or_double_original_is_rejected(tmp_path):
    with pytest.raises(IngestError):
        ingest.run(tmp_path, make_settings(tmp_path))
    (tmp_path / "original.mp4").write_bytes(b"")
    (tmp_path / "original.mov").write_bytes(b"")
    with pytest.raises(IngestError):
        ingest.run(tmp_path, make_settings(tmp_path))


def test_run_ffmpeg_without_binary(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("no ffmpeg here")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(IngestError, match="not installed"):
        ingest.run_ffmpeg(["ffmpeg", "-version"])
