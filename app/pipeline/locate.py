"""Find the part of a step: Muse Spark picks the moment and points, SAM 3.1 cuts inside the box.

A word alone often fails: SAM does not find a "back cover" that Spark points at without trouble.
So the order is: Spark chooses the frames of the step where the part shows best, points at it
(a box on the 0..1000 grid), SAM cuts it out inside that box, and Spark checks the cut-out on a
zoomed tile. A cut-out that fails any check is not shown: no mark is better than a wrong mark.
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

PICK_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "pick_frame_v1.md"
MOMENTS = 6  # frames of the step shown to Spark
PICK_SIDE = 640  # long side of those frames
GRABS = 3  # frames read around each moment, the sharpest is kept
MIN_CONFIDENCE = 0.6  # a good cut-out scored 0.97 on a real video, a wrong one 0.46
MIN_FILL = 0.25  # share of the box the cut-out must fill
MAX_AREA = 0.85  # a box over nearly the whole frame points at nothing

PICK_SCHEMA = {
    "type": "object",
    "properties": {"frames": {"type": "array", "items": {"type": "integer"}}},
    "required": ["frames"],
    "additionalProperties": False,
}


@dataclass
class Located:
    """The part of a step, cut out and checked."""

    t_s: float
    frame: np.ndarray
    box: tuple[int, int, int, int]  # 0..1000 grid
    confidence: float
    detection: Detection
    size_sent: tuple[int, int]


def moments(start_s: float, end_s: float, count: int = MOMENTS) -> list[float]:
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
    factor = PICK_SIDE / max(height, width)
    if factor >= 1:
        return frame
    return cv2.resize(frame, (int(width * factor), int(height * factor)), cv2.INTER_AREA)


def _write(frame: np.ndarray, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88]):
        raise ValueError(f"cannot write {path.name}")
    return path


def pick_frames(
    client: Any, settings: Settings, frames: list, part: str, context: str, work: Path
) -> list[int]:
    """Positions in ``frames`` where Spark sees the part best, best first."""
    paths = [_write(_small(frame), work / f"moment{n}.jpg") for n, (_, frame) in enumerate(frames)]
    prompt = (
        PICK_PROMPT.read_text(encoding="utf-8")
        .replace("<<CONTEXT>>", context)
        .replace("<<COUNT>>", str(len(frames)))
        .replace("<<PART>>", part)
    )
    data = spark.ask_json(
        client, settings, name="pick_frames", schema=PICK_SCHEMA, prompt=prompt, images=paths
    )
    chosen = data.get("frames") if isinstance(data, dict) else None
    if not isinstance(chosen, list):
        return []
    return [n - 1 for n in chosen if isinstance(n, int) and 1 <= n <= len(frames)][:2]


def _clean_box(box: tuple) -> bool:
    x1, y1, x2, y2 = box
    area = max(0, x2 - x1) * max(0, y2 - y1) / 1_000_000
    return x2 - x1 >= 4 and y2 - y1 >= 4 and area <= MAX_AREA


def cut_and_check(
    client: Any,
    settings: Settings,
    path: Path,
    frame: np.ndarray,
    part: str,
    context: str,
    tried: dict,
) -> tuple[tuple[int, int, int, int], float, Detection, tuple[int, int]] | None:
    """Spark points on one frame, SAM cuts, Spark checks. ``tried`` records what happened."""
    pointed = client.ground(path, part, context=context, max_boxes=1)
    if not pointed:
        tried["result"] = "Spark does not see it"
        return None
    box = tuple(int(value) for value in pointed[0].box)
    tried["box"] = list(box)
    if not _clean_box(box):
        tried["result"] = "unusable box"
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


def locate_part(
    client: Any,
    settings: Settings,
    job_dir: Path,
    step: Step,
    part: str,
    context: str,
    work: Path,
) -> Located | None:
    """The part of the step, on the frame where it shows best, or None when it cannot be proven."""
    record: dict[str, Any] = {"part": part, "tries": []}
    located = None
    try:
        frames = read_moments(job_dir / "video.mp4", moments(step.start_s, step.end_s))
        if frames:
            chosen = pick_frames(client, settings, frames, part, context, work)
            record["picked"] = [round(frames[n][0], 2) for n in chosen]
            for n in chosen:
                t_s, frame = frames[n]
                tried: dict[str, Any] = {"t_s": round(t_s, 2)}
                record["tries"].append(tried)
                path = _write(frame, work / f"try{n}.jpg")
                try:
                    kept = cut_and_check(client, settings, path, frame, part, context, tried)
                except BudgetExceeded:
                    raise
                except MetaError as exc:
                    tried["result"] = f"failed: {exc}"
                    continue
                if kept is not None:
                    box, confidence, detection, size = kept
                    located = Located(t_s, frame, box, confidence, detection, size)
                    break
    finally:
        relative = f"steps/{step.index:02d}_part.json"
        artifacts.write_text_atomic(job_dir / relative, json.dumps(record, indent=2))
    return located
