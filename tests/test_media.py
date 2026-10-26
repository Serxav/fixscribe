"""Stills from the original: native pixels, rotation and HDR handled."""

import shutil

import cv2
import pytest

from app.pipeline import ingest, media
from tests.video_factory import make_video

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def mean_saturation_png(path):
    frame = cv2.imread(str(path))
    assert frame is not None
    return float(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 1].mean())


def test_still_keeps_native_resolution(tmp_path):
    src = make_video(tmp_path / "original.mp4", size=(640, 360), seconds=2, audio=False)
    source = ingest.probe_source(src)
    dst = tmp_path / "still.png"
    assert media.extract_still(src, source, 1.0, dst) == (640, 360)
    assert dst.exists()
    assert list(tmp_path.glob("*.tmp.png")) == []


def test_still_max_side_caps_without_upscaling(tmp_path):
    src = make_video(tmp_path / "original.mp4", size=(1280, 720), seconds=2, audio=False)
    source = ingest.probe_source(src)
    assert media.extract_still(src, source, 1.0, tmp_path / "big.png", max_side=640) == (640, 360)
    small = make_video(tmp_path / "small.mp4", size=(320, 180), seconds=2, audio=False)
    assert media.extract_still(small, ingest.probe_source(small), 1.0, tmp_path / "s.png", 640) == (
        320,
        180,
    )


def test_rotated_still_is_portrait_at_native_size(tmp_path):
    src = make_video(
        tmp_path / "original.mov", size=(1920, 1080), seconds=2, audio=False, rotation=90
    )
    source = ingest.probe_source(src)
    assert source.rotation == 90
    assert media.extract_still(src, source, 1.0, tmp_path / "still.png") == (1080, 1920)


def test_hdr_still_matches_sdr_saturation(tmp_path):
    sdr = make_video(tmp_path / "sdr.mp4", size=(640, 360), seconds=3, audio=False)
    hdr = make_video(tmp_path / "hdr.mov", size=(640, 360), seconds=3, audio=False, hdr=True)
    sdr_png = tmp_path / "sdr.png"
    hdr_png = tmp_path / "hdr.png"
    media.extract_still(sdr, ingest.probe_source(sdr), 1.5, sdr_png)
    media.extract_still(hdr, ingest.probe_source(hdr), 1.5, hdr_png)
    assert mean_saturation_png(hdr_png) == pytest.approx(mean_saturation_png(sdr_png), rel=0.15)


def test_extract_stills_writes_one_png_per_time(tmp_path):
    src = make_video(tmp_path / "original.mp4", size=(320, 180), seconds=3, audio=False)
    source = ingest.probe_source(src)
    paths = media.extract_stills(src, source, [0.5, 1.5, 2.5], tmp_path / "stills")
    assert len(paths) == 3
    assert all(path.exists() for path in paths)
    assert [path.name for path in paths] == ["still_001.png", "still_002.png", "still_003.png"]


def test_negative_time_is_rejected(tmp_path):
    src = make_video(tmp_path / "original.mp4", size=(320, 180), seconds=1, audio=False)
    with pytest.raises(ValueError, match="t must be"):
        media.extract_still(src, ingest.probe_source(src), -1.0, tmp_path / "x.png")
