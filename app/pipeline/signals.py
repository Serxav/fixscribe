"""Visual-signals stage: motion and scene-change signals from the video."""

import math
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from app import artifacts
from app.config import Settings
from app.schemas import Candidate, Signals


class SignalsError(Exception):
    """Raised when the signals inputs cannot be read."""


SAMPLE_FPS = 4
PROXY_WIDTH = 160
MIN_PAUSE_S = 0.75
MIN_GAP_S = 2.0
EDGE_S = 1.0


def sample_frames(video: Path) -> Iterator[tuple[float, np.ndarray]]:
    """Yield ``(t_seconds, frame_bgr)`` at about ``SAMPLE_FPS``, reading sequentially."""
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            return
        src_fps = capture.get(cv2.CAP_PROP_FPS)
        if not src_fps or math.isnan(src_fps) or math.isinf(src_fps) or src_fps <= 0:
            src_fps = 30.0
        step = max(1, round(src_fps / SAMPLE_FPS))
        frame_index = 0
        while True:
            if not capture.grab():
                break
            if frame_index % step == 0:
                ok, frame = capture.retrieve()
                if not ok or frame is None:
                    break
                t_seconds = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
                if not math.isfinite(t_seconds) or t_seconds < 0:
                    t_seconds = 0.0
                height, width = frame.shape[:2]
                if width != PROXY_WIDTH and width > 0:
                    new_height = max(1, int(round(height * PROXY_WIDTH / width)))
                    frame = cv2.resize(
                        frame, (PROXY_WIDTH, new_height), interpolation=cv2.INTER_AREA
                    )
                yield (t_seconds, frame)
            frame_index += 1
    finally:
        capture.release()


def compensated_motion_energy(prev_gray: np.ndarray, curr_gray: np.ndarray) -> tuple[float, float]:
    """Return ``(compensated, raw)`` mean abs difference divided by 255.

    The global shift between the frames is estimated with phase correlation and the
    previous frame is warped by it before the difference, so pure camera shake does
    not look like hand activity. The compensated difference ignores a border of
    ``ceil(max(|dx|, |dy|))`` pixels, where the warp has no real data.
    """
    if prev_gray.shape != curr_gray.shape:
        curr_gray = cv2.resize(curr_gray, (prev_gray.shape[1], prev_gray.shape[0]))
    raw = float(cv2.absdiff(curr_gray, prev_gray).mean()) / 255.0
    try:
        (dx, dy), _response = cv2.phaseCorrelate(
            prev_gray.astype(np.float32), curr_gray.astype(np.float32)
        )
    except cv2.error:
        return raw, raw
    if not (math.isfinite(dx) and math.isfinite(dy)):
        return raw, raw
    height, width = prev_gray.shape[:2]
    matrix = np.float32([[1.0, 0.0, float(dx)], [0.0, 1.0, float(dy)]])
    aligned = cv2.warpAffine(
        prev_gray,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    diff = cv2.absdiff(aligned, curr_gray)
    border = int(math.ceil(max(abs(float(dx)), abs(float(dy)))))
    if border > 0 and height > 2 * border and width > 2 * border:
        diff = diff[border:-border, border:-border]
    compensated = float(diff.mean()) / 255.0
    return compensated, raw


def compute_signals(video: Path) -> Signals:
    """Return the motion and scene signals of ``video`` in one sampling pass."""
    motion: list[list[float]] = []
    scene: list[list[float]] = []
    prev_gray: np.ndarray | None = None
    prev_hist: np.ndarray | None = None
    timestamps: list[float] = []

    for t_seconds, frame in sample_frames(video):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_gray is None:
            motion_energy = 0.0
        else:
            motion_energy, _raw = compensated_motion_energy(prev_gray, gray)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 1.0, 0.0, cv2.NORM_L1)
        if prev_hist is None:
            scene_score = 0.0
        else:
            scene_score = float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
        motion.append([round(float(t_seconds), 4), round(float(motion_energy), 4)])
        scene.append([round(float(t_seconds), 4), round(float(scene_score), 4)])
        prev_gray = gray
        prev_hist = hist
        timestamps.append(float(t_seconds))

    if not motion:
        raise SignalsError("cannot read video.mp4")

    if len(timestamps) > 1:
        sample_interval = timestamps[1] - timestamps[0]
        if not math.isfinite(sample_interval) or sample_interval <= 0:
            sample_interval = 1.0 / SAMPLE_FPS
    else:
        sample_interval = 1.0 / SAMPLE_FPS
    duration_s = timestamps[-1] + sample_interval

    candidate_dicts = rank_candidates(
        find_pauses(motion) + find_scene_changes(scene),
        float(duration_s),
    )
    candidates = [
        Candidate(t=float(c["t"]), kind=c["kind"], score=float(c["score"])) for c in candidate_dicts
    ]
    return Signals(
        fps=float(SAMPLE_FPS),
        duration_s=round(float(duration_s), 4),
        motion=motion,
        scene=scene,
        candidates=candidates,
    )


def smooth(values: list[float], window: int = 3) -> list[float]:
    """Return the centered moving average of ``values`` with the same length."""
    if window <= 1 or not values:
        return list(values)
    half = window // 2
    result: list[float] = []
    for i in range(len(values)):
        start = max(0, i - half)
        end = min(len(values), i + half + 1)
        chunk = values[start:end]
        result.append(sum(chunk) / len(chunk))
    return result


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return _percentile(values, 50.0)


def find_pauses(motion: list[list[float]], min_len_s: float = MIN_PAUSE_S) -> list[dict]:
    """Return pause candidates from runs below the threshold on the smoothed curve."""
    if not motion:
        return []
    times = [float(row[0]) for row in motion]
    values = [float(row[1]) for row in motion]
    smoothed = smooth(values)
    p35 = _percentile(smoothed, 35.0)
    median = _median(smoothed)
    absolute = max(0.004, p35)
    if median > 0:
        threshold = min(absolute, 0.5 * median)
        # A threshold at zero would hide a genuinely still video; keep the floor.
        if threshold <= 0:
            threshold = absolute
    else:
        threshold = absolute
    if len(times) > 1:
        interval = (times[-1] - times[0]) / (len(times) - 1)
        if interval <= 0:
            interval = 1.0 / SAMPLE_FPS
    else:
        interval = 1.0 / SAMPLE_FPS

    candidates: list[dict] = []
    run_start: int | None = None
    for i, value in enumerate(smoothed):
        if value < threshold:
            if run_start is None:
                run_start = i
        elif run_start is not None:
            _append_pause(
                candidates, times, smoothed, run_start, i - 1, threshold, interval, min_len_s
            )
            run_start = None
    if run_start is not None:
        _append_pause(
            candidates,
            times,
            smoothed,
            run_start,
            len(smoothed) - 1,
            threshold,
            interval,
            min_len_s,
        )
    return candidates


def find_scene_changes(scene: list[list[float]]) -> list[dict]:
    """Return scene candidates at local peaks above an adaptive threshold."""
    if len(scene) < 3:
        return []
    times = [float(row[0]) for row in scene]
    values = [float(row[1]) for row in scene]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    threshold = max(0.3, mean + 3 * math.sqrt(variance))
    candidates: list[dict] = []
    for i in range(1, len(values) - 1):
        score = values[i]
        if score > threshold and score > values[i - 1] and score > values[i + 1]:
            candidates.append({"t": times[i], "kind": "scene", "score": min(1.0, score)})
    return candidates


def rank_candidates(candidates: list[dict], duration_s: float) -> list[dict]:
    """Drop edge candidates and resolve conflicts closer than ``MIN_GAP_S``."""
    filtered = [
        dict(candidate)
        for candidate in candidates
        if EDGE_S <= float(candidate["t"]) <= duration_s - EDGE_S
    ]
    filtered.sort(key=lambda candidate: float(candidate["t"]))
    kept: list[dict] = []
    for candidate in filtered:
        if kept and float(candidate["t"]) - float(kept[-1]["t"]) < MIN_GAP_S:
            if float(candidate["score"]) > float(kept[-1]["score"]):
                kept[-1] = candidate
        else:
            kept.append(candidate)
    kept.sort(key=lambda candidate: float(candidate["t"]))
    return kept


def run(job_dir: Path, settings: Settings) -> Signals:
    """Compute the visual signals of ``video.mp4`` and write ``signals.json``."""
    del settings
    video = job_dir / "video.mp4"
    if not video.is_file():
        raise SignalsError("missing video.mp4")
    result = compute_signals(video)
    artifacts.save(job_dir, result)
    return result


def _percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (percent / 100.0) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[int(position)])
    fraction = position - lower
    return float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction)


def _append_pause(
    candidates: list[dict],
    times: list[float],
    values: list[float],
    start: int,
    end: int,
    threshold: float,
    interval: float,
    min_len_s: float,
) -> None:
    run_len = end - start + 1
    if run_len * interval < min_len_s:
        return
    center = (times[start] + times[end]) / 2
    mean_in_run = sum(values[start : end + 1]) / run_len
    score = min(1.0, max(0.0, 1 - mean_in_run / threshold)) if threshold > 0 else 0.0
    candidates.append({"t": round(float(center), 4), "kind": "pause", "score": round(score, 3)})
