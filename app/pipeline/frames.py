"""Keyframe and clip stage: sharpest frame and short loop clip per step."""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2

from app.config import Settings
from app.schemas import Guide, Step

logger = logging.getLogger(__name__)


class FramesError(Exception):
    """Raised when the frames inputs cannot be read."""


CLIP_SECONDS = 6.0
WINDOW_S = 1.0
SAMPLE_FPS = 5


def sharpness(image: Any) -> float:
    """Return the variance of the Laplacian of the grayscale image."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def key_moment(step: Step) -> float:
    """Return the first video evidence time inside the step, else its middle."""
    for item in step.evidence:
        if item.source == "video" and step.start_s <= item.t_s <= step.end_s:
            return item.t_s
    return (step.start_s + step.end_s) / 2


def best_frame(capture: cv2.VideoCapture, start_s: float, end_s: float) -> tuple[float, Any] | None:
    """Return the (t, frame) with the highest sharpness, or None if no frame reads."""
    best: tuple[float, Any] | None = None
    best_score = float("-inf")
    step_s = 1 / SAMPLE_FPS
    t = start_s
    while t <= end_s + 1e-9:
        capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = capture.read()
        if ok and frame is not None:
            score = sharpness(frame)
            if score > best_score:
                best_score = score
                best = (t, frame)
        t += step_s
    return best


def clip_range(step: Step, keyframe_s: float, duration_s: float) -> tuple[float, float]:
    """Return the (start, length) of the step clip around the keyframe."""
    length = min(CLIP_SECONDS, step.end_s - step.start_s)
    start = keyframe_s - length / 2
    start = max(start, step.start_s)
    start = min(start, step.end_s - length)
    start = max(start, 0.0)
    start = min(start, max(duration_s - length, 0.0))
    return (start, length)


def cut_clip(video: Path, start: float, length: float, dst: Path) -> None:
    """Cut a silent re-encoded clip with ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        str(start),
        "-i",
        str(video),
        "-t",
        str(length),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise FramesError(f"ffmpeg timed out cutting {dst.name}") from exc
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.splitlines()[-3:])
        raise FramesError(f"ffmpeg failed cutting {dst.name}:\n{tail}")


def run(job_dir: Path, settings: Settings) -> Guide:
    """Save the sharpest frame and a short clip per step, then update guide.json."""
    del settings
    video_path = job_dir / "video.mp4"
    guide_path = job_dir / "guide.json"
    if not video_path.is_file():
        raise FramesError("missing video.mp4")
    if not guide_path.is_file():
        raise FramesError("missing guide.json")
    try:
        guide = Guide.model_validate_json(guide_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FramesError(f"broken guide.json: {exc}") from None
    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise FramesError("cannot open video.mp4")
        duration_s = _duration_s(capture, guide)
        steps_dir = job_dir / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)
        updated = []
        for step in guide.steps:
            try:
                updated.append(_process_step(capture, video_path, steps_dir, step, duration_s))
            except Exception as exc:
                logger.warning("frames: skipping step %d: %s", step.index, exc)
                updated.append(step)
        guide = guide.model_copy(update={"steps": updated})
        _write_guide_atomic(guide_path, guide)
        return guide
    finally:
        capture.release()


def _process_step(
    capture: cv2.VideoCapture,
    video_path: Path,
    steps_dir: Path,
    step: Step,
    duration_s: float,
) -> Step:
    """Save the best frame and clip of one step, and return the updated step."""
    key = key_moment(step)
    found = best_frame(capture, max(key - WINDOW_S, step.start_s), min(key + WINDOW_S, step.end_s))
    if found is None:
        raise FramesError(f"no readable frame for step {step.index}")
    keyframe_s, frame = found
    name = f"{step.index:02d}"
    image_path = steps_dir / f"{name}.jpg"
    if not cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85]):
        raise FramesError(f"cannot write {image_path.name}")
    clip_path = steps_dir / f"{name}.mp4"
    clip_start, clip_length = clip_range(step, keyframe_s, duration_s)
    cut_clip(video_path, clip_start, clip_length, clip_path)
    return step.model_copy(
        update={
            "keyframe_s": round(float(keyframe_s), 2),
            "image": f"steps/{name}.jpg",
            "clip": f"steps/{name}.mp4",
        }
    )


def _duration_s(capture: cv2.VideoCapture, guide: Guide) -> float:
    """Return the video duration in seconds."""
    if guide.duration_s is not None and guide.duration_s > 0:
        return float(guide.duration_s)
    fps = capture.get(cv2.CAP_PROP_FPS)
    count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    if fps > 0 and count > 0:
        return count / fps
    if guide.steps:
        return max(step.end_s for step in guide.steps)
    raise FramesError("cannot determine the video duration")


def _write_guide_atomic(path: Path, guide: Guide) -> None:
    with tempfile.NamedTemporaryFile(
        dir=str(path.parent),
        delete=False,
        mode="w",
        suffix=".tmp",
        encoding="utf-8",
    ) as tmp:
        json.dump(guide.model_dump(mode="json"), tmp)
        tmp_path = tmp.name
    os.replace(tmp_path, path)
