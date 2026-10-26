"""Tests for the keyframe and clip stage."""

import shutil
import subprocess

import cv2
import numpy as np
import pytest

from app import artifacts
from app.artifacts import ArtifactError
from app.config import Settings
from app.pipeline import frames, ingest
from app.pipeline.frames import FramesError
from app.schemas import Evidence, Frames, IngestInfo, Plan, Step

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


def _part_pattern(width=100, height=70, cell=10):
    part = np.full((height, width, 3), 180, dtype=np.uint8)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if (x // cell + y // cell) % 2 == 0:
                part[y : y + cell, x : x + cell] = (20, 20, 20)
    return part


def _base_frame():
    frame = np.full((240, 320, 3), 180, dtype=np.uint8)
    frame[85:155, 110:210] = _part_pattern()
    return frame


def _trap_frame(kind):
    if kind == "A":
        return _base_frame()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    for y in range(0, 240, 16):
        for x in range(0, 320, 16):
            if (x // 16 + y // 16) % 2 == 0:
                frame[y : y + 16, x : x + 16] = (255, 255, 255)
    frame[48:192, 64:256] = (180, 180, 180)
    blurred = cv2.GaussianBlur(_part_pattern(), (21, 21), 0)
    blurred = cv2.GaussianBlur(blurred, (21, 21), 0)
    frame[85:155, 110:210] = blurred
    return frame


def _encode_frames(path, images, fps=8):
    src = path.parent / f"{path.stem}_src"
    src.mkdir(parents=True, exist_ok=True)
    for index, image in enumerate(images):
        assert cv2.imwrite(str(src / f"{index:03d}.png"), image)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(src / "%03d.png"),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "10",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=120,
    )


def _custom_job(tmp_path, images, step, fps=8, duration_s=4.0):
    _encode_frames(tmp_path / "video.mp4", images, fps=fps)
    artifacts.save(tmp_path, _plan([step], duration_s=duration_s))
    return Settings(model_api_key="", data_dir=tmp_path)


@needs_ffmpeg
def test_busy_background_trap(tmp_path):
    a_frame, b_frame = _trap_frame("A"), _trap_frame("B")
    assert frames.sharpness(b_frame) > frames.sharpness(a_frame)
    assert frames.roi_sharpness(a_frame) > frames.roi_sharpness(b_frame)
    images = [_trap_frame("A" if (i // 4) % 2 == 0 else "B") for i in range(32)]
    settings = _custom_job(tmp_path, images, _step(1, 0.0, 4.0))
    result = frames.run(tmp_path, settings)
    assert int(result.steps[0].keyframe_s // 0.5) % 2 == 0  # an A half-second


@needs_ffmpeg
def test_steadiness_picks_steady_half(tmp_path):
    rng = np.random.default_rng(42)
    base = _base_frame()
    images = []
    for i in range(32):
        if i < 16:
            dx, dy = int(rng.integers(-6, 7)), int(rng.integers(-6, 7))
            matrix = np.float32([[1, 0, dx], [0, 1, dy]])
            images.append(cv2.warpAffine(base, matrix, (320, 240), borderMode=cv2.BORDER_REPLICATE))
        else:
            images.append(base.copy())
    settings = _custom_job(tmp_path, images, _step(1, 0.0, 4.0))
    result = frames.run(tmp_path, settings)
    assert result.steps[0].keyframe_s >= 2.0


@needs_ffmpeg
def test_hand_blob_loses_to_uncovered_frame(tmp_path):
    base = _base_frame()
    covered = base.copy()
    cv2.rectangle(covered, (90, 70), (230, 170), (120, 150, 200), thickness=-1)
    assert frames.hand_fraction(covered) > 0.3
    assert frames.hand_fraction(base) < 0.05
    images = [covered.copy() if i < 16 else base.copy() for i in range(32)]
    settings = _custom_job(tmp_path, images, _step(1, 0.0, 4.0))
    result = frames.run(tmp_path, settings)
    assert result.steps[0].keyframe_s >= 2.0


@needs_ffmpeg
def test_native_still_and_display_jpeg_sizes(tmp_path):
    for name, size in (("original.mp4", "1080x1920"), ("video.mp4", "720x1280")):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc=size={size}:rate=30",
                "-t",
                "2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(tmp_path / name),
            ],
            check=True,
            timeout=120,
        )
    source = ingest.probe_source(tmp_path / "original.mp4")
    artifacts.save(
        tmp_path,
        IngestInfo(
            duration_s=2.0, width=720, height=1280, has_audio=False, fps=30.0, source=source
        ),
    )
    artifacts.save(tmp_path, _plan([_step(1, 0.0, 2.0)], duration_s=2.0))
    result = frames.run(tmp_path, Settings(model_api_key="", data_dir=tmp_path))
    media = result.steps[0]
    assert media.still == "stills/01.png"
    still = cv2.imread(str(tmp_path / media.still))
    assert still is not None and still.shape[:2] == (1920, 1080)
    image = cv2.imread(str(tmp_path / media.image))
    assert image is not None and max(image.shape[:2]) <= 1600


@needs_ffmpeg
def test_missing_original_falls_back_to_proxy(tmp_path):
    settings = _write_job(tmp_path, _plan([_step(1, 0.0, 3.0)]), duration=3.0)
    result = frames.run(tmp_path, settings)
    assert result.steps[0].still is None
    assert (tmp_path / result.steps[0].image).is_file()
