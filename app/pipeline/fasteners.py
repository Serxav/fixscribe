"""Fasteners: find the screws, bolts, pins... a step puts in or takes out, and where they are.

One method, used by the perception stage (guides) and the step check (user photos):

1. PROPOSE: SAM 3.1 looks for the fastener word on the whole frame and on four overlapping,
   enlarged quarters of it (sliced inference, so a few-pixel screw becomes visible).
2. CHOOSE: Muse Spark never gives coordinates. It sees every candidate numbered on a zoomed
   contact sheet and only says which numbers really are that fastener (set-of-mark prompting).
3. FOLLOW: SAM 3.1 video follows each chosen fastener through the whole step clip.
4. DECIDE: a fastener counts only if the track sees it steadily where it was chosen, and it was
   absent at the other end of the step (put in when building, taken out when taking apart).

A fastener that is not clearly visible is never invented: the count then comes from the
analysis alone and the guide says so.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import artifacts
from app.domains import profile_for
from app.pipeline.ingest import run_ffmpeg
from app.pipeline.verify import MAX_TILES, confirm
from app.schemas import Identity, Step
from app.text import ARTICLES

logger = logging.getLogger(__name__)

CLIP_FRAMES = 120  # SAM video bills per frame: a whole step in at most this many frames
MAX_FPS = 10
MIN_FPS = 2
SEED_SHARE = 0.3  # the fasteners are chosen in the last 30 % of a build step (first, taking apart)
MIN_CONFIDENCE = 0.3
MAX_SIDE = 0.12  # a fastener box bigger than this share of the frame is not a fastener
SAME = 0.5  # boxes overlapping more than this (IoU) are the same fastener
STEADY = 0.5  # seen in at least half the frames of its end of the step
ABSENT = 0.2  # seen in at most a fifth of the frames at the other end
ZOOM_SIDE = 1280  # every region is enlarged to this long side before SAM looks at it
FASTENER_WORDS = ("screw", "bolt", "nut", "dowel", "pin", "washer", "clip", "rivet", "peg", "stud")

Box = tuple[float, float, float, float]  # left, top, right, bottom in clip pixels


@dataclass
class Found:
    """What the method kept for one step, in the pixels of the step clip."""

    fps: float
    start_s: float
    size: tuple[int, int]
    seed: int  # the clip frame where the fasteners were chosen (and are drawn)
    frames: dict[int, dict[int, Box]] = field(default_factory=dict)  # frame -> id -> box
    kept: list[int] = field(default_factory=list)  # fastener ids put in / taken out, in order
    confidence: dict[int, float] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "fps": self.fps,
            "start_s": self.start_s,
            "size": list(self.size),
            "seed": self.seed,
            "kept": self.kept,
            "confidence": {str(k): v for k, v in self.confidence.items()},
            "frames": {
                str(index): {str(oid): [round(v, 1) for v in box] for oid, box in boxes.items()}
                for index, boxes in self.frames.items()
            },
        }

    @classmethod
    def from_json(cls, data: dict) -> "Found":
        return cls(
            fps=float(data["fps"]),
            start_s=float(data["start_s"]),
            size=(int(data["size"][0]), int(data["size"][1])),
            seed=int(data["seed"]),
            kept=[int(k) for k in data["kept"]],
            confidence={int(k): float(v) for k, v in data.get("confidence", {}).items()},
            frames={
                int(index): {int(oid): tuple(box) for oid, box in boxes.items()}
                for index, boxes in data["frames"].items()
            },
        )

    def boxes_at(self, t: float) -> dict[int, Box]:
        """The kept fasteners in the clip frame closest to video time ``t`` (empty outside)."""
        index = round((t - self.start_s) * self.fps)
        if not self.frames or index < 0 or index > max(self.frames):
            return {}
        return {oid: box for oid, box in self.frames.get(index, {}).items() if oid in self.kept}


def found_path(job_dir: Path, index: int) -> Path:
    return job_dir / "steps" / f"{index:02d}_fasteners.json"


def save_found(job_dir: Path, index: int, found: Found) -> None:
    artifacts.write_json_atomic(found_path(job_dir, index), found.to_json())


def load_found(job_dir: Path, index: int) -> Found | None:
    path = found_path(job_dir, index)
    if not path.is_file():
        return None
    try:
        return Found.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (KeyError, TypeError, ValueError):
        return None


def _clean_phrase(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = "".join(
        ch if ch.isalnum() or ch.isspace() or ch == "-" else " " for ch in text.lower()
    )
    words = [word for word in cleaned.split() if word not in ARTICLES]
    if not words:
        return None
    return " ".join(words[-2:])


def fastener_concept(job_dir: Path) -> str:
    """The job-wide fastener word: the domain profile kind, or "screw"."""
    identity = artifacts.load_optional(job_dir, Identity)
    if identity is None:
        return "screw"
    return profile_for(identity.category).fastener_kind


def step_fastener(step: Step, default: str) -> str:
    """The fastener this step handles, as SAM should search it ("allen bolt", "dowel").

    The job-wide word ("screw") misses an assembly that uses bolts in one step and dowels in
    the next, so the step's own fastener name wins when it has one.
    """
    for name in step.removes or []:
        phrase = _clean_phrase(name)
        if phrase and any(word in phrase.split()[-1] for word in FASTENER_WORDS):
            return phrase
    return default


# 1. PROPOSE ---------------------------------------------------------------------------------


def regions(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """The whole frame, then four overlapping quarters (each 60 % of a side)."""
    w, h = int(width * 0.6), int(height * 0.6)
    return [
        (0, 0, width, height),
        (0, 0, w, h),
        (width - w, 0, width, h),
        (0, height - h, w, height),
        (width - w, height - h, width, height),
    ]


def _iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _segment_region(
    client: Any, image: np.ndarray, region: tuple[int, int, int, int], concept: str, path: Path
) -> list[tuple[float, Box]]:
    x1, y1, x2, y2 = region
    crop = image[y1:y2, x1:x2]
    scale = ZOOM_SIDE / max(crop.shape[:2])
    zoomed = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    with artifacts.atomic_path(path) as tmp:
        if not cv2.imwrite(str(tmp), zoomed):
            raise OSError(f"cannot write {path.name}")
    detections, sent = client.segment(path, concept)
    sx = zoomed.shape[1] / max(1, sent[0]) / scale
    sy = zoomed.shape[0] / max(1, sent[1]) / scale
    out = []
    for item in detections:
        confidence = item.confidence if item.confidence is not None else 0.5
        left, top, right, bottom = item.box
        box = (x1 + left * sx, y1 + top * sy, x1 + right * sx, y1 + bottom * sy)
        if box[2] > box[0] and box[3] > box[1]:
            out.append((confidence, box))
    return out


def propose(
    client: Any, image: np.ndarray, concept: str, work: Path, area: Box | None = None
) -> list[tuple[float, Box]]:
    """SAM's fastener candidates on ``image`` (inside ``area`` if given), most confident first."""
    height, width = image.shape[:2]
    limit = MAX_SIDE * max(width, height)
    words = [concept] + ([concept.split()[-1]] if " " in concept else [])
    for word in words:  # SAM knows "bolt" better than "allen bolt": the last word is the fallback
        found: list[tuple[float, Box]] = []
        for n, region in enumerate(regions(width, height)):
            found += _segment_region(client, image, region, word, work / f"region{n}.png")
        kept: list[tuple[float, Box]] = []
        for confidence, box in sorted(found, key=lambda item: -item[0]):
            if confidence < MIN_CONFIDENCE or max(box[2] - box[0], box[3] - box[1]) > limit:
                continue
            if area is not None and not _inside(box, area):
                continue
            if all(_iou(box, other) <= SAME for _, other in kept):
                kept.append((confidence, box))
        if kept:
            return kept[:MAX_TILES]
    return []


def _inside(box: Box, area: Box) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return area[0] <= cx <= area[2] and area[1] <= cy <= area[3]


# 2. CHOOSE ----------------------------------------------------------------------------------


def choose(
    client: Any,
    model: str,
    image: np.ndarray,
    candidates: list[tuple[float, Box]],
    fastener: str,
    context: str,
) -> list[tuple[float, Box]]:
    """Spark picks, by number, the candidates that really are ``fastener``."""
    if not candidates or not model or not hasattr(client, "respond"):
        return candidates
    height, width = image.shape[:2]
    marks = [
        {
            "label": fastener,
            "cut_box": [
                round(box[0] * 1000 / width),
                round(box[1] * 1000 / height),
                round(box[2] * 1000 / width),
                round(box[3] * 1000 / height),
            ],
        }
        for _, box in candidates
    ]
    checked = confirm(client, model, image, marks, context)
    return [item for item, mark in zip(candidates, checked, strict=True) if mark["checked"]]


# 3. FOLLOW ----------------------------------------------------------------------------------


def clip_fps(length_s: float) -> float:
    """Frames per second for a step clip: the whole step in at most CLIP_FRAMES frames."""
    if length_s <= 0:
        return float(MAX_FPS)
    return float(min(MAX_FPS, max(MIN_FPS, CLIP_FRAMES / length_s)))


def cut_step_clip(video: Path, start_s: float, end_s: float, fps: float, dst: Path) -> None:
    """The whole step at ``fps``, full size: the exact frames SAM sees and we draw on."""
    with artifacts.atomic_path(dst) as tmp:
        run_ffmpeg(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}",
             "-i", str(video), "-an", "-vf", f"fps={fps:g}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
             str(tmp)]
        )  # fmt: skip


def read_frames(path: Path) -> list[np.ndarray]:
    capture = cv2.VideoCapture(str(path))
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    return frames


def sharpest(frames: list[np.ndarray], first: int, last: int) -> int:
    """The least blurry frame in [first, last)."""
    best, best_score = first, -1.0
    for index in range(first, max(first + 1, last)):
        gray = cv2.cvtColor(frames[index], cv2.COLOR_BGR2GRAY)
        score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if score > best_score:
            best, best_score = index, score
    return best


def follow(
    client: Any, clip: Path, size: tuple[int, int], boxes: list[Box], seed: int
) -> dict[int, dict[int, Box]]:
    """SAM video follows each box from the seed frame: frame -> id -> box (clip pixels)."""
    prompts = [
        (oid, seed, tuple(int(round(v)) for v in box)) for oid, box in enumerate(boxes, start=1)
    ]
    tracks = client.segment_video(clip, boxes=prompts, size=size)
    limit = MAX_SIDE * max(size)
    frames: dict[int, dict[int, Box]] = {}
    for frame in tracks:
        sx = size[0] / frame.width if frame.width else 1.0
        sy = size[1] / frame.height if frame.height else 1.0
        for obj in frame.objects:
            x1, y1, x2, y2 = obj.box
            box = (x1 * sx, y1 * sy, x2 * sx, y2 * sy)
            if 0 < box[2] - box[0] <= limit and 0 < box[3] - box[1] <= limit:
                frames.setdefault(frame.frame, {})[obj.object_id] = box
    return frames


# 4. DECIDE ----------------------------------------------------------------------------------


def decide(
    frames: dict[int, dict[int, Box]], ids: list[int], count: int, adding: bool
) -> list[int]:
    """The ids seen steadily at their end of the step and absent at the other end."""
    window = max(1, round(count * SEED_SHARE))
    end = range(count - window, count)
    start = range(0, window)
    here, there = (end, start) if adding else (start, end)

    def share(oid: int, span: range) -> float:
        return sum(1 for index in span if oid in frames.get(index, {})) / len(span)

    return [oid for oid in ids if share(oid, here) >= STEADY and share(oid, there) <= ABSENT]


def reading_order(boxes: dict[int, Box], height: int) -> list[int]:
    """Ids top to bottom (rows a twentieth of the frame tall), then left to right."""
    row = max(1.0, height / 20)
    return sorted(
        boxes, key=lambda oid: (round((boxes[oid][1] + boxes[oid][3]) / 2 / row), boxes[oid][0])
    )


def find_in_step(
    client: Any,
    model: str,
    video: Path,
    step: Step,
    fastener: str,
    context: str,
    adding: bool,
    work: Path,
    duration_s: float,
) -> tuple[Found, np.ndarray] | None:
    """Run the four stages on one step. Returns what was kept and the seed frame, or None."""
    end_s = min(step.end_s, duration_s) if duration_s else step.end_s
    if end_s - step.start_s <= 0:
        return None
    fps = clip_fps(end_s - step.start_s)
    work.mkdir(parents=True, exist_ok=True)
    clip = work / "clip.mp4"
    cut_step_clip(video, step.start_s, end_s, fps, clip)
    frames = read_frames(clip)
    if len(frames) < 3:
        return None
    height, width = frames[0].shape[:2]
    window = max(1, round(len(frames) * SEED_SHARE))
    seed = (
        sharpest(frames, len(frames) - window, len(frames))
        if adding
        else sharpest(frames, 0, window)
    )
    found = Found(fps=fps, start_s=step.start_s, size=(width, height), seed=seed)
    candidates = propose(client, frames[seed], fastener, work)
    chosen = choose(client, model, frames[seed], candidates, fastener, context)
    if not chosen:
        return found, frames[seed]
    found.frames = follow(client, clip, (width, height), [box for _, box in chosen], seed)
    ids = list(range(1, len(chosen) + 1))
    kept = decide(found.frames, ids, len(frames), adding)
    if step.screws and step.screws.count:  # never more than the analysis counted
        kept = sorted(kept, key=lambda oid: -chosen[oid - 1][0])[: step.screws.count]
    at_seed = {oid: chosen[oid - 1][1] for oid in kept}
    found.kept = reading_order(at_seed, height)
    found.confidence = {oid: round(chosen[oid - 1][0], 2) for oid in found.kept}
    found.frames.setdefault(seed, {}).update(at_seed)  # drawn exactly where it was chosen
    return found, frames[seed]
