"""Keyframe and clip stage: pick the frame where the part is best seen.

Candidates are sampled from the proxy ``video.mp4`` every 0.25 s over the
whole step. Each candidate is scored with

    score = z(roi_sharpness) + 0.5 * z(steadiness) - 1.0 * hand_fraction * 3

where ``roi_sharpness`` is the variance of the Laplacian on the central ROI
(middle 60 % of width and height) of the gray frame, ``steadiness`` is
``1 - motion_energy`` from ``signals.json`` at the nearest sample time (or,
without signals, one minus the frame difference with the previous
candidate), and ``hand_fraction`` is the share of ROI pixels inside a skin
range in YCrCb (Cr 133-173, Cb 77-127). The z-scores are computed within
the step, so the three terms are comparable. Ties go to the candidate
closer to the step's video evidence time, then to the middle of the step.

The display JPEG comes from a native-resolution still taken from the
original upload; when the original cannot give a still, the proxy frame is
used and ``still`` stays ``None``.
"""

import logging
import math
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import cv2

from app import artifacts
from app.config import Settings
from app.pipeline import media
from app.pipeline.ingest import find_original, probe_source
from app.schemas import Frames, IngestInfo, Plan, Signals, SourceVideo, Step, StepMedia

logger = logging.getLogger(__name__)

VERSION = "2"


class FramesError(Exception):
    """Raised when the frames inputs cannot be read."""


CLIP_SECONDS = 6.0
SAMPLE_INTERVAL_S = 0.25
ROI_FRACTION = 0.6
DISPLAY_MAX_SIDE = 1600
JPEG_QUALITY = 88
SKIN_CR = (133, 173)
SKIN_CB = (77, 127)


@dataclass(frozen=True)
class Candidate:
    """One sampled frame of a step and its score terms."""

    t: float
    roi_sharpness: float
    steadiness: float
    hand_fraction: float
    score: float = 0.0


def sharpness(image: Any) -> float:
    """Return the variance of the Laplacian of the grayscale image."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _central_roi(image: Any) -> Any:
    height, width = image.shape[:2]
    roi_w = max(1, int(round(width * ROI_FRACTION)))
    roi_h = max(1, int(round(height * ROI_FRACTION)))
    x0 = (width - roi_w) // 2
    y0 = (height - roi_h) // 2
    return image[y0 : y0 + roi_h, x0 : x0 + roi_w]


def roi_sharpness(image: Any) -> float:
    """Return the Laplacian variance on the central ROI only, never the whole frame."""
    gray = cv2.cvtColor(_central_roi(image), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def hand_fraction(image: Any) -> float:
    """Return the share of ROI pixels inside the YCrCb skin range."""
    roi = _central_roi(image)
    ycrcb = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
    mask = cv2.inRange(
        ycrcb,
        (0, SKIN_CR[0], SKIN_CB[0]),
        (255, SKIN_CR[1], SKIN_CB[1]),
    )
    return float(cv2.countNonZero(mask)) / float(mask.size)


def key_moment(step: Step) -> float:
    """Return the first video evidence time inside the step, else its middle."""
    for item in step.evidence:
        if item.source == "video" and step.start_s <= item.t_s <= step.end_s:
            return item.t_s
    return (step.start_s + step.end_s) / 2


def _zscores(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(variance)
    if std < 1e-12:
        return [0.0] * len(values)
    return [(value - mean) / std for value in values]


def score_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Fill in ``score`` for each candidate: ``z(sharp) + 0.5*z(steady) - 3*hand``."""
    sharp_z = _zscores([candidate.roi_sharpness for candidate in candidates])
    steady_z = _zscores([candidate.steadiness for candidate in candidates])
    return [
        replace(
            candidate,
            score=sharp + 0.5 * steady - 1.0 * candidate.hand_fraction * 3,
        )
        for candidate, sharp, steady in zip(candidates, sharp_z, steady_z, strict=True)
    ]


def choose_candidate(candidates: list[Candidate], step: Step) -> Candidate:
    """Return the best candidate; ties go to the evidence time, then the middle."""
    evidence_s = key_moment(step)
    middle_s = (step.start_s + step.end_s) / 2
    best: Candidate | None = None
    for candidate in candidates:
        if best is None or candidate.score > best.score + 1e-9:
            best = candidate
        elif abs(candidate.score - best.score) <= 1e-9:
            candidate_key = (
                abs(candidate.t - evidence_s),
                abs(candidate.t - middle_s),
            )
            best_key = (abs(best.t - evidence_s), abs(best.t - middle_s))
            if candidate_key < best_key:
                best = candidate
    if best is None:
        raise FramesError(f"no readable frame for step {step.index}")
    return best


def _motion_at(motion: list[list[float]], t: float) -> float:
    return min(motion, key=lambda row: abs(float(row[0]) - t))[1]


def evaluate_candidates(
    capture: cv2.VideoCapture,
    step: Step,
    signals: Signals | None = None,
) -> list[Candidate]:
    """Sample and score the candidates of one step from the proxy capture.

    Timestamps come from ``CAP_PROP_POS_MSEC`` read right after the seek,
    which is the timestamp of the frame the seek landed on.
    """
    motion = signals.motion if signals is not None and signals.motion else None
    raw: list[Candidate] = []
    diffs: list[float | None] = []
    prev_roi_gray: Any = None
    t = step.start_s
    while t <= step.end_s + 1e-9:
        capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        pos_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
        ok, frame = capture.read()
        if ok and frame is not None:
            actual_s = pos_ms / 1000.0 if math.isfinite(pos_ms) and pos_ms >= 0 else t
            if raw and abs(actual_s - raw[-1].t) < 1e-6:
                t += SAMPLE_INTERVAL_S
                continue
            roi_gray = cv2.cvtColor(_central_roi(frame), cv2.COLOR_BGR2GRAY)
            if motion is not None:
                steadiness = 1.0 - float(_motion_at(motion, actual_s))
                diffs.append(None)
            else:
                steadiness = 0.0
                if prev_roi_gray is None:
                    diffs.append(None)
                else:
                    diff = float(cv2.absdiff(roi_gray, prev_roi_gray).mean()) / 255.0
                    diffs.append(diff)
            raw.append(
                Candidate(
                    t=actual_s,
                    roi_sharpness=float(cv2.Laplacian(roi_gray, cv2.CV_64F).var()),
                    steadiness=steadiness,
                    hand_fraction=hand_fraction(frame),
                )
            )
            prev_roi_gray = roi_gray
        t += SAMPLE_INTERVAL_S
    if motion is None and raw:
        known = [diff for diff in diffs if diff is not None]
        first_diff = known[0] if known else 0.0
        raw = [
            replace(candidate, steadiness=1.0 - (diff if diff is not None else first_diff))
            for candidate, diff in zip(raw, diffs, strict=True)
        ]
    return score_candidates(raw)


def best_frame(
    capture: cv2.VideoCapture,
    step: Step | float,
    end_s: float | None = None,
) -> tuple[float, Any] | None:
    """Return the (t, frame) of the chosen candidate, or None if no frame reads."""
    if not isinstance(step, Step):
        if end_s is None:
            raise TypeError("best_frame needs a Step or a start and an end")
        step = Step(index=1, title="", instruction="", start_s=float(step), end_s=end_s)
    candidates = evaluate_candidates(capture, step)
    if not candidates:
        return None
    chosen = choose_candidate(candidates, step)
    frame = _frame_at(capture, chosen.t)
    if frame is None:
        return None
    return (chosen.t, frame)


def _frame_at(capture: cv2.VideoCapture, t: float) -> Any | None:
    capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = capture.read()
    if ok and frame is not None:
        return frame
    return None


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
        "20",
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


def run(job_dir: Path, settings: Settings) -> Frames:
    """Pick the best frame per step and cut its clip (frames.json)."""
    del settings
    video_path = job_dir / "video.mp4"
    if not video_path.is_file():
        raise FramesError("missing video.mp4")
    plan = artifacts.load(job_dir, Plan)
    signals = _load_signals(job_dir)
    original_source = _original_source(job_dir)
    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise FramesError("cannot open video.mp4")
        steps_dir = job_dir / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)
        media = []
        for step in plan.steps:
            try:
                media.append(
                    _process_step(
                        capture,
                        job_dir,
                        video_path,
                        step,
                        plan.duration_s,
                        signals,
                        original_source,
                    )
                )
            except Exception as exc:
                # One bad step must not cost the whole guide its photos.
                logger.warning("frames: skipping step %d: %s", step.index, exc)
        frames = Frames(steps=media)
        artifacts.save(job_dir, frames)
        return frames
    finally:
        capture.release()


def _load_signals(job_dir: Path) -> Signals | None:
    try:
        return artifacts.load_optional(job_dir, Signals)
    except Exception as exc:
        logger.warning("frames: ignoring signals.json: %s", exc)
        return None


def _original_source(job_dir: Path) -> tuple[Path, SourceVideo] | None:
    """Return (original, source) for native stills, or None when unavailable."""
    try:
        original = find_original(job_dir)
    except Exception as exc:
        logger.warning("frames: original still unavailable: %s", exc)
        return None
    try:
        info = artifacts.load_optional(job_dir, IngestInfo)
        if info is not None and info.source is not None:
            return (original, info.source)
        return (original, probe_source(original))
    except Exception as exc:
        logger.warning("frames: original source unavailable: %s", exc)
        return None


def _process_step(
    capture: cv2.VideoCapture,
    job_dir: Path,
    video_path: Path,
    step: Step,
    duration_s: float,
    signals: Signals | None,
    original_source: tuple[Path, SourceVideo] | None,
) -> StepMedia:
    """Save the best frame and clip of one step."""
    candidates = evaluate_candidates(capture, step, signals)
    if not candidates:
        raise FramesError(f"no readable frame for step {step.index}")
    chosen = choose_candidate(candidates, step)
    keyframe_s = min(max(round(float(chosen.t), 2), step.start_s), step.end_s)
    name = f"{step.index:02d}"
    steps_dir = job_dir / "steps"
    still_rel, display = _still_and_display(job_dir, name, keyframe_s, original_source)
    if display is None:
        display = _frame_at(capture, keyframe_s)
        if display is None:
            raise FramesError(f"no readable frame for step {step.index}")
    _write_display_jpeg_atomic(steps_dir / f"{name}.jpg", display)
    clip_path = steps_dir / f"{name}.mp4"
    clip_start, clip_length = clip_range(step, keyframe_s, duration_s)
    with artifacts.atomic_path(clip_path) as tmp_clip:
        cut_clip(video_path, clip_start, clip_length, tmp_clip)
    return StepMedia(
        index=step.index,
        keyframe_s=keyframe_s,
        image=f"steps/{name}.jpg",
        clip=f"steps/{name}.mp4",
        still=still_rel,
    )


def _still_and_display(
    job_dir: Path,
    name: str,
    keyframe_s: float,
    original_source: tuple[Path, SourceVideo] | None,
) -> tuple[str | None, Any | None]:
    """Take the native still from the original; (None, None) means use the proxy."""
    if original_source is None:
        return (None, None)
    original, source = original_source
    still_path = job_dir / "stills" / f"{name}.png"
    try:
        media.extract_still(original, source, keyframe_s, still_path)
    except Exception as exc:
        logger.warning("frames: still %s from original failed: %s", name, exc)
        still_path.unlink(missing_ok=True)
        return (None, None)
    display = cv2.imread(str(still_path))
    if display is None:
        logger.warning("frames: still %s from original is unreadable", name)
        still_path.unlink(missing_ok=True)
        return (None, None)
    return (f"stills/{name}.png", display)


def _write_display_jpeg_atomic(path: Path, frame: Any) -> None:
    """Write a display JPEG (long side <= 1600 px, quality 88) atomically."""
    image = frame
    height, width = image.shape[:2]
    long_side = max(width, height)
    if long_side > DISPLAY_MAX_SIDE:
        scale = DISPLAY_MAX_SIDE / long_side
        image = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    with artifacts.atomic_path(path) as tmp:
        if not cv2.imwrite(str(tmp), image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]):
            raise FramesError(f"cannot write {path.name}")
