"""Tests for the keyframe and clip stage."""

import shutil
import subprocess

import cv2
import pytest

from app import artifacts
from app.artifacts import ArtifactError
from app.config import Settings
from app.pipeline import frames
from app.pipeline.frames import FramesError
from app.schemas import Evidence, Frames, Plan, Step

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
needs_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not installed"
)


def _make_video(path, duration=6.0):
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=720x1280:rate=30",
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, check=True, timeout=120)


def _step(index, start, end, evidence=None):
    return Step(
        index=index,
        title=f"Step {index}",
        instruction=f"Do step {index}.",
        start_s=start,
        end_s=end,
        evidence=evidence or [],
    )


def _plan(steps, duration_s=6.0):
    return Plan(title="Guide", device="Phone", mode="silent", duration_s=duration_s, steps=steps)


def _write_job(job_dir, plan, duration=6.0):
    _make_video(job_dir / "video.mp4", duration)
    artifacts.save(job_dir, plan)
    return Settings(model_api_key="", data_dir=job_dir)


@needs_ffmpeg
def test_run_writes_frames_and_clips(tmp_path):
    steps = [_step(1, 0.0, 3.0), _step(2, 3.0, 6.0)]
    settings = _write_job(tmp_path, _plan(steps))
    result = frames.run(tmp_path, settings)
    for step, media in zip(steps, result.steps, strict=True):
        assert media.index == step.index
        assert media.image == f"steps/{step.index:02d}.jpg"
        assert media.clip == f"steps/{step.index:02d}.mp4"
        assert (tmp_path / media.image).is_file()
        assert (tmp_path / media.clip).is_file()
        assert step.start_s <= media.keyframe_s <= step.end_s
        assert abs(media.keyframe_s - (step.start_s + step.end_s) / 2) <= 1.0
    assert artifacts.load(tmp_path, Frames) == result
    assert not (tmp_path / "guide.json").exists()  # frames never touches the guide
    assert not list((tmp_path / "steps").glob(".*"))  # no temp files left


@needs_ffmpeg
@needs_ffprobe
def test_clip_is_short_and_silent(tmp_path):
    settings = _write_job(tmp_path, _plan([_step(1, 0.0, 3.0), _step(2, 3.0, 6.0)]))
    frames.run(tmp_path, settings)
    clip = str(tmp_path / "steps" / "01.mp4")
    duration = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            clip,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert float(duration.stdout.strip()) == pytest.approx(3.0, abs=0.5)
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", clip],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert "audio" not in streams.stdout.strip().splitlines()


@needs_ffmpeg
def test_sharpness_prefers_original(tmp_path):
    settings = _write_job(tmp_path, _plan([_step(1, 0.0, 3.0), _step(2, 3.0, 6.0)]))
    frames.run(tmp_path, settings)
    image = cv2.imread(str(tmp_path / "steps" / "01.jpg"))
    assert image is not None
    blurred = cv2.GaussianBlur(image, (21, 21), 0)
    assert frames.sharpness(image) > frames.sharpness(blurred)


def test_key_moment_prefers_video_evidence_inside_step():
    step = _step(
        1,
        0.0,
        3.0,
        evidence=[
            Evidence(t_s=1.0, source="audio", text="talking"),
            Evidence(t_s=5.0, source="video", text="later"),
            Evidence(t_s=2.0, source="video", text="here"),
        ],
    )
    assert frames.key_moment(step) == 2.0


def test_key_moment_falls_back_to_middle():
    assert frames.key_moment(_step(1, 0.0, 3.0)) == 1.5
    audio_only = _step(1, 0.0, 3.0, [Evidence(t_s=1.0, source="audio", text="talking")])
    assert frames.key_moment(audio_only) == 1.5
    outside = _step(1, 0.0, 3.0, [Evidence(t_s=5.0, source="video", text="later")])
    assert frames.key_moment(outside) == 1.5


def test_clip_range_starts_at_step_start():
    assert frames.clip_range(_step(1, 0.0, 20.0), 0.0, 20.0) == (0.0, 6.0)


@needs_ffmpeg
def test_step_past_video_end_is_skipped(tmp_path):
    settings = _write_job(tmp_path, _plan([_step(1, 0.0, 3.0), _step(2, 100.0, 103.0)]))
    result = frames.run(tmp_path, settings)
    assert [media.index for media in result.steps] == [1]  # step 2 has no frame: no media
    assert (tmp_path / "steps" / "01.jpg").is_file()


@needs_ffmpeg
def test_missing_plan_raises(tmp_path):
    _make_video(tmp_path / "video.mp4")
    settings = Settings(model_api_key="", data_dir=tmp_path)
    with pytest.raises(ArtifactError, match="missing plan.json"):
        frames.run(tmp_path, settings)


def test_missing_video_raises(tmp_path):
    artifacts.save(tmp_path, _plan([_step(1, 0.0, 3.0)]))
    settings = Settings(model_api_key="", data_dir=tmp_path)
    with pytest.raises(FramesError, match="video.mp4"):
        frames.run(tmp_path, settings)
