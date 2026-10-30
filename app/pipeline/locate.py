"""Find the part of a step: Muse Spark picks the moment and points, SAM 3.1 cuts inside the box.

A word alone often fails: SAM does not find a "back cover" that Spark points at without trouble.
And a wide shot hides what matters: a phone on a desk is a small part of the frame. So the order
is: Spark points at the object being worked on and every frame is zoomed on it; Spark chooses the
frames of the step where the part shows best, points at it (a box on the 0..1000 grid), SAM cuts
it out inside that box, and Spark checks the cut-out on a zoomed tile. A cut-out that fails any
check is not shown: no mark is better than a wrong mark.
Every attempt is saved in ``steps/NN_part.json``, so a miss can be explained without a new call.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import artifacts, spark
from app.agent.tools import full_mask
from app.config import Settings
from app.meta_client import BudgetExceeded, Detection, MetaError
from app.pipeline import verify
from app.schemas import Step

logger = logging.getLogger(__name__)

REVIEW_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "step_review_v1.md"
REVIEW_SIDE = 800  # long side of the frames of the review
REVIEW_PAD_S = 2.0  # the review also sees a little before and after the step
GRABS = 3  # frames read around each moment, the sharpest is kept
MIN_CONFIDENCE = 0.6  # a good cut-out scored 0.97 on a real video, a wrong one 0.46
MIN_FILL = 0.25  # share of the box the cut-out must fill
MAX_AREA = 0.85  # a box over nearly the whole frame points at nothing
ZOOM_SIDE = 1280  # long side of a zoomed frame
ZOOM_PAD = 0.15  # room kept around the object, as a share of its size
MIN_ZOOM = 0.3  # never zoom on less than this share of the frame's width or height
REVIEW_FRAMES = 12  # frames of a step Spark goes through one by one
SLOW_BOX = 28  # half a box around a pointed small part, on the 0..1000 grid
WORK_MARGIN = 60  # how far from the spot being worked on a pointed part may be, on the same grid
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {"type": "boolean"},
        "instruction": {"type": "string"},
        "start_s": {"type": "number"},
        "end_s": {"type": "number"},
        "confidence": {"type": "number"},
        "part_frames": {"type": "array", "items": {"type": "integer"}},
        "work_frame": {"type": "integer"},
        "work_x": {"type": "integer"},
        "work_y": {"type": "integer"},
        "fastener_frame": {"type": "integer"},
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "matches",
        "instruction",
        "start_s",
        "end_s",
        "confidence",
        "part_frames",
        "work_frame",
        "work_x",
        "work_y",
        "fastener_frame",
        "points",
    ],
    "additionalProperties": False,
}


@dataclass
class Located:
    """The part of a step, cut out and checked."""

    t_s: float
    frame: np.ndarray
    box: tuple[int, int, int, int]  # 0..1000 grid of the whole video frame
    confidence: float
    detection: Detection
    size_sent: tuple[int, int]
    area: tuple[int, int, int, int] | None = None  # the zoom, 0..1000 grid of the video frame


def moments(start_s: float, end_s: float, count: int = REVIEW_FRAMES) -> list[float]:
    """Seconds spread evenly inside a step, away from its two edges."""
    span = max(0.0, end_s - start_s)
    return [round(start_s + span * (n + 0.5) / count, 2) for n in range(count)]


def _sharpness(frame: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def read_moments(video: Path, times: list[float]) -> list[tuple[float, np.ndarray]]:
    """The sharpest frame around each second; a second the video cannot give is left out."""
    capture = cv2.VideoCapture(str(video))
    found = []
    try:
        for t in times:
            grabs = []
            for offset in range(GRABS):
                at = t + offset * 0.15
                capture.set(cv2.CAP_PROP_POS_MSEC, at * 1000)
                ok, frame = capture.read()
                if ok:
                    grabs.append((_sharpness(frame), at, frame))
            if grabs:
                _, at, frame = max(grabs, key=lambda item: item[0])
                found.append((at, frame))
    finally:
        capture.release()
    return found


def _small(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    factor = REVIEW_SIDE / max(height, width)
    if factor >= 1:
        return frame
    return cv2.resize(frame, (int(width * factor), int(height * factor)), cv2.INTER_AREA)


def _write(frame: np.ndarray, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88]):
        raise ValueError(f"cannot write {path.name}")
    return path


def review_step(
    client: Any,
    settings: Settings,
    step: Step,
    part: str,
    kind: str,
    context: str,
    frames: list,
    work: Path,
) -> dict | None:
    """Spark goes through the zoomed frames in order; None when it gives no usable answer."""
    paths = []
    for n, (t_s, frame) in enumerate(frames):
        stamped = _small(frame).copy()
        cv2.putText(stamped, f"{t_s:.1f} s", (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (255, 255, 255), 2, cv2.LINE_AA)  # fmt: skip
        paths.append(_write(stamped, work / f"review{n}.jpg"))
    count = step.screws.count if step.screws else 0
    prompt = REVIEW_PROMPT.read_text(encoding="utf-8")
    for key, value in {
        "CONTEXT": context,
        "INSTRUCTION": step.instruction,
        "START": f"{step.start_s:.1f}",
        "END": f"{step.end_s:.1f}",
        "PART": part or "none",
        "KIND": kind,
        "COUNT": str(count),
        "N": str(len(frames)),
    }.items():
        prompt = prompt.replace(f"<<{key}>>", value)
    for _ in range(2):  # a bad answer happens now and then: one more try is cheap
        try:
            data = spark.ask_json(
                client,
                settings,
                name="step_review",
                schema=REVIEW_SCHEMA,
                prompt=prompt,
                images=paths,
                raw_path=work.parent / f"{step.index:02d}_review_raw.txt",
            )
        except spark.SparkAnswerError:
            continue
        if isinstance(data, dict) and isinstance(data.get("matches"), bool):
            return data
    return None


def work_area(
    client: Any, path: Path, context: str, record: dict
) -> tuple[int, int, int, int] | None:
    """Where the object being worked on is, with some room around it; None for the whole frame."""
    query = "the object being repaired or built, not the table, the mat, hands or loose tools"
    try:
        pointed = client.ground(path, query, context=context, max_boxes=1)
    except BudgetExceeded:
        raise
    except MetaError as exc:
        record["zoom"] = f"failed: {exc}"
        return None
    if not pointed:
        record["zoom"] = "Spark does not see it"
        return None
    x1, y1, x2, y2 = (float(value) for value in pointed[0].box)
    half_w = max((x2 - x1) * (1 + 2 * ZOOM_PAD), MIN_ZOOM * 1000) / 2
    half_h = max((y2 - y1) * (1 + 2 * ZOOM_PAD), MIN_ZOOM * 1000) / 2
    centre_x, centre_y = (x1 + x2) / 2, (y1 + y2) / 2
    centre_x = min(max(centre_x, half_w), 1000 - half_w) if half_w < 500 else 500
    centre_y = min(max(centre_y, half_h), 1000 - half_h) if half_h < 500 else 500
    area = (
        int(max(0, centre_x - half_w)),
        int(max(0, centre_y - half_h)),
        int(min(1000, centre_x + half_w)),
        int(min(1000, centre_y + half_h)),
    )
    record["zoom"] = list(area)
    return area


def zoomed(frame: np.ndarray, area: tuple[int, int, int, int] | None) -> np.ndarray:
    """The frame cut to ``area`` and enlarged, a little sharpened so edges stay readable."""
    if area is None:
        return frame
    height, width = frame.shape[:2]
    crop = frame[
        area[1] * height // 1000 : max(area[1] * height // 1000 + 1, area[3] * height // 1000),
        area[0] * width // 1000 : max(area[0] * width // 1000 + 1, area[2] * width // 1000),
    ]
    factor = ZOOM_SIDE / max(crop.shape[:2])
    large = cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    return cv2.addWeighted(large, 1.4, cv2.GaussianBlur(large, (0, 0), 2), -0.4, 0)


def to_full(
    box: tuple[int, int, int, int], area: tuple[int, int, int, int] | None
) -> tuple[int, int, int, int]:
    """A box on a zoomed frame, back on the 0..1000 grid of the whole video frame."""
    if area is None:
        return box
    w, h = area[2] - area[0], area[3] - area[1]
    return (
        area[0] + box[0] * w // 1000,
        area[1] + box[1] * h // 1000,
        area[0] + box[2] * w // 1000,
        area[1] + box[3] * h // 1000,
    )


def _clean_box(box: tuple) -> bool:
    x1, y1, x2, y2 = box
    area = max(0, x2 - x1) * max(0, y2 - y1) / 1_000_000
    return x2 - x1 >= 4 and y2 - y1 >= 4 and area <= MAX_AREA


def _touches(box: tuple, spot: tuple[int, int]) -> bool:
    """True when the spot is inside the box, give or take ``WORK_MARGIN``."""
    x1, y1, x2, y2 = box
    return (
        x1 - WORK_MARGIN <= spot[0] <= x2 + WORK_MARGIN
        and y1 - WORK_MARGIN <= spot[1] <= y2 + WORK_MARGIN
    )


def work_spot(review: dict, count: int) -> tuple[int, tuple[int, int]] | None:
    """The frame number and the spot the review saw the tool or fingers touch, if any."""
    n, x, y = review.get("work_frame"), review.get("work_x"), review.get("work_y")
    if not all(isinstance(value, int) for value in (n, x, y)):
        return None
    if not 1 <= n <= count or not (0 <= x <= 1000 and 0 <= y <= 1000):
        return None
    return n, (x, y)


def cut_and_check(
    client: Any,
    settings: Settings,
    path: Path,
    frame: np.ndarray,
    part: str,
    context: str,
    tried: dict,
    near: tuple[int, int] | None = None,
) -> tuple[tuple[int, int, int, int], float, Detection, tuple[int, int]] | None:
    """Spark points on one frame, SAM cuts, Spark checks. ``tried`` records what happened.

    ``near`` is the spot being worked on: there can be several parts of the same kind, and the
    one that counts is the one under the tool.
    """
    if near is not None:
        context += f" The tool or fingers touch it at about x={near[0]}, y={near[1]} (0-1000 grid)."
    pointed = client.ground(path, part, context=context, max_boxes=1)
    if not pointed:
        tried["result"] = "Spark does not see it"
        return None
    box = tuple(int(value) for value in pointed[0].box)
    tried["box"] = list(box)
    if not _clean_box(box):
        tried["result"] = "unusable box"
        return None
    if near is not None and not _touches(box, near):
        tried["result"] = "another part, away from the spot being worked on"
        return None
    detections, size = client.segment_boxes(path, [box])
    if not detections:
        tried["result"] = "SAM cut nothing"
        return None
    detection = detections[0]
    confidence = float(detection.confidence or 0.0)
    tried["confidence"] = round(confidence, 3)
    mask = full_mask(detection, size, frame.shape)
    height, width = frame.shape[:2]
    box_area = max(1.0, (box[2] - box[0]) * width / 1000 * (box[3] - box[1]) * height / 1000)
    fill = float(mask.sum()) / box_area if mask is not None else 0.0
    tried["fill"] = round(fill, 3)
    if confidence < MIN_CONFIDENCE or fill < MIN_FILL:
        tried["result"] = "weak cut-out"
        return None
    outline = _outline(mask, width, height)
    mark = {"label": part, "cut_box": box, "outline": outline}
    image = verify.tile(frame, mark, f"1: {part}")
    prompt = verify._prompt(verify.PART_PROMPT, context, part)
    verdict = verify._ask(client, settings.spark_model, prompt, [image]).get(1, {})
    tried["why"] = str(verdict.get("why", ""))
    if verdict.get("real") is not True:
        tried["result"] = "Spark rejected the cut-out"
        return None
    tried["result"] = "kept"
    return box, confidence, detection, size


def _outline(mask: np.ndarray, width: int, height: int) -> list[list[int]]:
    """The cut-out's largest contour on the 0..1000 grid, for the check tile."""
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return []
    points = max(contours, key=cv2.contourArea).reshape(-1, 2)[::4]
    return [[int(x * 1000 / width), int(y * 1000 / height)] for x, y in points]


@dataclass
class StepLook:
    """What the close look at one step found."""

    review: dict | None = None
    located: Located | None = None
    frames: list | None = None
    area: tuple[int, int, int, int] | None = None


def look_at_step(
    client: Any,
    settings: Settings,
    job_dir: Path,
    step: Step,
    part: str,
    kind: str,
    context: str,
    work: Path,
) -> StepLook:
    """Zoom on the object, review the step frame by frame, cut out its part on the best frame."""
    record: dict[str, Any] = {"part": part, "tries": []}
    look = StepLook()
    try:
        first = max(0.0, step.start_s - REVIEW_PAD_S)
        wide = read_moments(job_dir / "video.mp4", moments(first, step.end_s + REVIEW_PAD_S))
        if not wide:
            return look
        middle = _write(wide[len(wide) // 2][1], work / "wide.jpg")
        look.area = work_area(client, middle, context, record)
        look.frames = [(t_s, zoomed(frame, look.area)) for t_s, frame in wide]
        look.review = review_step(client, settings, step, part, kind, context, look.frames, work)
        if look.review is None:
            record["review"] = "no usable answer"
            return look
        record["review"] = look.review
        chosen = look.review.get("part_frames") or []
        chosen = [n for n in chosen if isinstance(n, int) and 1 <= n <= len(look.frames)][:3]
        spot = work_spot(look.review, len(look.frames))
        near = spot[1] if spot else None
        if spot:  # the frame where the tool touches it comes first: its spot is exact there
            chosen = [spot[0], *(n for n in chosen if n != spot[0])][:3]
        for n in chosen:
            t_s, frame = look.frames[n - 1]
            tried: dict[str, Any] = {"t_s": round(t_s, 2)}
            record["tries"].append(tried)
            path = _write(frame, work / f"try{n}.jpg")
            try:
                kept = cut_and_check(client, settings, path, frame, part, context, tried, near)
            except BudgetExceeded:
                raise
            except MetaError as exc:
                tried["result"] = f"failed: {exc}"
                continue
            if kept is not None:
                box, confidence, detection, size = kept
                look.located = Located(
                    t_s, frame, to_full(box, look.area), confidence, detection, size, look.area
                )
                break
    finally:
        relative = f"steps/{step.index:02d}_part.json"
        artifacts.write_text_atomic(job_dir / relative, json.dumps(record, indent=2))
    return look


@dataclass
class SlowLook:
    """Small parts Spark pointed at during the review, cut out and checked."""

    t_s: float
    frame: np.ndarray
    boxes: list[tuple[int, int, int, int]]  # 0..1000 grid of ``frame``
    confidences: list[float]


def cut_pointed(
    client: Any, settings: Settings, look: StepLook, kind: str, count: int, context: str, work: Path
) -> SlowLook | None:
    """SAM cuts each small part the review pointed at; Spark checks each one on a zoomed tile."""
    review = look.review or {}
    n = review.get("fastener_frame", 0)
    points = review.get("points") or []
    if not look.frames or not isinstance(n, int) or not 1 <= n <= len(look.frames) or not points:
        return None
    t_s, frame = look.frames[n - 1]
    path = _write(frame, work / "fasteners.jpg")
    boxes, confidences = [], []
    for point in points[:count]:
        x, y = int(point["x"]), int(point["y"])
        box = (
            max(0, x - SLOW_BOX),
            max(0, y - SLOW_BOX),
            min(1000, x + SLOW_BOX),
            min(1000, y + SLOW_BOX),
        )
        detections, size = client.segment_boxes(path, [box])
        if not detections or (detections[0].confidence or 0.0) < MIN_CONFIDENCE:
            continue
        cut = detections[0].box
        tight = (
            int(cut[0] * 1000 / size[0]),
            int(cut[1] * 1000 / size[1]),
            int(cut[2] * 1000 / size[0]),
            int(cut[3] * 1000 / size[1]),
        )
        image = verify.tile(frame, {"label": kind, "cut_box": tight}, f"1: {kind}")
        prompt_check = verify._prompt(verify.PART_PROMPT, context, kind)
        verdict = verify._ask(client, settings.spark_model, prompt_check, [image]).get(1, {})
        if verdict.get("real") is True:
            boxes.append(tight)
            confidences.append(float(detections[0].confidence))
    return SlowLook(t_s, frame, boxes, confidences) if boxes else None
