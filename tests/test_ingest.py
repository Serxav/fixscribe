"""Ingest stage tests: tiny clips are built with ffmpeg, no fixtures committed."""

import hashlib
import json
import shutil
import subprocess
import wave

import cv2
import pytest

from app import artifacts
from app.config import Settings
from app.pipeline import ingest
from app.pipeline.ingest import IngestError
from app.schemas import IngestInfo
from tests.video_factory import make_video

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


def stream_field(path, field):
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            f"stream={field}",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def mean_saturation(path, t=1.5):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    cap.release()
    assert ok
    return float(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 1].mean())


def test_landscape_with_audio(tmp_path):
    make_clip(tmp_path / "original.mp4", "1920x1080")
    info = ingest.run(tmp_path, make_settings(tmp_path))
    assert isinstance(info, IngestInfo)
    assert (info.width, info.height) == (1280, 720)
    assert info.has_audio
    assert info.fps == pytest.approx(30)
    assert info.source is not None and info.source.filename == "original.mp4"
    assert info.duration_s == pytest.approx(2, abs=0.2)
    assert read_wav_info(tmp_path / "audio.wav") == (1, 24000, 2)
    assert artifacts.load(tmp_path, IngestInfo) == info


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
    assert artifacts.load(tmp_path, IngestInfo).has_audio is False


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


def test_vfr_source_becomes_cfr_with_true_timestamps(tmp_path):
    src = make_video(
        tmp_path / "original.mp4", size=(640, 360), fps=60, seconds=3, audio=False, vfr=True
    )
    source = ingest.probe_source(src)
    assert source.vfr is True
    info = ingest.run(tmp_path, make_settings(tmp_path))
    out = tmp_path / "video.mp4"
    assert stream_field(out, "avg_frame_rate") == "30/1"
    assert stream_field(out, "r_frame_rate") == "30/1"
    assert info.duration_s == pytest.approx(source.duration_s, abs=0.1)
    cap = cv2.VideoCapture(str(out))
    fps = cap.get(cv2.CAP_PROP_FPS)
    assert fps == pytest.approx(30)
    index = 0
    while True:
        ok, _frame = cap.read()
        if not ok:
            break
        stamp_s = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        assert stamp_s == pytest.approx(index / fps, abs=0.05)
        index += 1
    cap.release()
    assert index > 60


def test_hdr_source_becomes_bt709_with_sdr_saturation(tmp_path):
    sdr_dir = tmp_path / "sdr"
    hdr_dir = tmp_path / "hdr"
    sdr_dir.mkdir()
    hdr_dir.mkdir()
    make_video(sdr_dir / "original.mp4", size=(640, 360), seconds=3, audio=False)
    hdr_src = make_video(
        hdr_dir / "original.mov", size=(640, 360), seconds=3, audio=False, hdr=True
    )
    assert ingest.probe_source(hdr_src).hdr is True
    ingest.run(sdr_dir, make_settings(sdr_dir))
    ingest.run(hdr_dir, make_settings(hdr_dir))
    out = hdr_dir / "video.mp4"
    assert stream_field(out, "color_primaries") == "bt709"
    assert stream_field(out, "color_transfer") == "bt709"
    sdr_sat = mean_saturation(sdr_dir / "video.mp4")
    hdr_sat = mean_saturation(out)
    assert hdr_sat == pytest.approx(sdr_sat, rel=0.15)


def test_rotated_source_reports_display_size(tmp_path):
    src = make_video(
        tmp_path / "original.mov", size=(1920, 1080), seconds=2, audio=False, rotation=90
    )
    source = ingest.probe_source(src)
    assert source.rotation == 90
    assert (source.width, source.height) == (1080, 1920)
    info = ingest.run(tmp_path, make_settings(tmp_path))
    assert (info.width, info.height) == (720, 1280)


def test_60fps_source_becomes_30fps(tmp_path):
    make_video(tmp_path / "original.mp4", size=(640, 360), fps=60, seconds=2, audio=False)
    info = ingest.run(tmp_path, make_settings(tmp_path))
    assert info.fps == pytest.approx(30)
    assert stream_field(tmp_path / "video.mp4", "avg_frame_rate") == "30/1"


def test_original_is_byte_identical_and_ingest_json_loads(tmp_path):
    src = make_video(tmp_path / "original.mp4", size=(640, 360), seconds=2, audio=True)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    info = ingest.run(tmp_path, make_settings(tmp_path))
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
    loaded = artifacts.load(tmp_path, IngestInfo)
    assert loaded == info
    raw = json.loads((tmp_path / "ingest.json").read_text(encoding="utf-8"))
    assert raw["source"]["filename"] == "original.mp4"
    assert raw["fps"] == pytest.approx(30)
