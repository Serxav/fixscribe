"""Fasteners: find the screws, bolts, pins... a step puts in or takes out, and where they are.

One method, used by the perception stage (guides) and the step check (user photos):

1. PROPOSE: SAM 3.1 looks for each fastener word on the whole frame and on four overlapping,
   enlarged quarters of it (sliced inference, so a few-pixel screw becomes visible), on two
   frames of the step's end (its start, when taking apart).
2. FOLLOW: SAM 3.1 video follows every candidate through the step, on a clip cropped and
   enlarged around the work area (small objects are tracked far better when bigger).
3. DECIDE: a candidate stays only if the track sees it steadily at its end of the step and
   clearly less at the other end (put in when building, taken out when taking apart).
4. CHOOSE: Muse Spark never gives coordinates. It sees each remaining candidate numbered, on
   up to three frames of the video, and says which numbers really are that fastener
   (set-of-mark prompting, several views per candidate).

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
from app.pipeline.verify import MAX_TILES, confirm_tracks
from app.schemas import Identity, Step
from app.text import ARTICLES

logger = logging.getLogger(__name__)

CLIP_FRAMES = 120  # SAM video bills per frame: a whole step in at most this many frames
MAX_FPS = 10
MIN_FPS = 2
SEED_SHARE = 0.3  # the fasteners are chosen in the last 30 % of a build step (first, taking apart)
LAST_SHARE = 0.1  # ...and again in its very last 10 %, where the finished state is
MIN_CONFIDENCE = 0.3
MAX_SIDE = 0.12  # a fastener box bigger than this share of the frame is not a fastener
SAME = 0.5  # boxes overlapping more than this (IoU) are the same fastener...
INSIDE = 0.6  # ...and so are boxes when this share of the smaller one lies in the other
STEADY = 0.5  # seen in at least half the frames of its end of the step
CHANGE = 0.5  # and in at least half more of them than at the other end (it really changed)
SCALE_1080 = "scale=w='if(gt(iw,ih),-2,min(1080,iw))':h='if(gt(iw,ih),min(1080,ih),-2)'"
ZOOM_SIDE = 1280  # every region is enlarged to this long side before SAM looks at it
MIN_AREA = 0.5  # the tracked work area is at least half the frame on each side...
AREA_MARGIN = 0.15  # ...and the candidates plus this share of the frame around them
VIEWS = 3  # frames of each candidate Spark sees
MAX_TRACKED = 16  # SAM video follows at most 16 prompted objects
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


def clean_phrase(text: str | None) -> str | None:
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
    return step_fasteners(step, default)[0]


def step_fasteners(step: Step, default: str) -> list[str]:
    """Every fastener the step names, at most two ("allen bolt", "washer"), else ``default``.

    A step that puts in "metal washers and hex nuts" shows whichever ends up visible.
    """
    kinds: list[str] = []
    for name in step.removes or []:
        phrase = clean_phrase(name)
        if phrase and any(word in phrase.split()[-1] for word in FASTENER_WORDS):
            if phrase not in kinds:
                kinds.append(phrase)
    return kinds[:2] or [default]


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


def same(a: Box, b: Box) -> bool:
    """True when two boxes are the same fastener (overlapping or one inside the other)."""
    if _iou(a, b) > SAME:
        return True
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return smaller > 0 and ix * iy / smaller >= INSIDE


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
            if not any(same(box, other) for _, other in kept):
                kept.append((confidence, box))
        if kept:
            return kept[:MAX_TILES]
    return []


def _inside(box: Box, area: Box) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return area[0] <= cx <= area[2] and area[1] <= cy <= area[3]


# 2. FOLLOW ----------------------------------------------------------------------------------


def clip_fps(length_s: float) -> float:
    """Frames per second for a step clip: the whole step in at most CLIP_FRAMES frames."""
    if length_s <= 0:
        return float(MAX_FPS)
    return float(min(MAX_FPS, max(MIN_FPS, CLIP_FRAMES / length_s)))


def cut_step_clip(
    video: Path, start_s: float, end_s: float, fps: float, dst: Path, prefilter: str = ""
) -> None:
    """The whole step at ``fps``, up to 1080p: the exact frames SAM sees and we draw on.

    ``video`` should be the original upload (the working copy is only 720p, too little for a
    small screw); ``prefilter`` is its colour conversion, if any.
    """
    chain = ",".join(part for part in (prefilter, f"fps={fps:g}", SCALE_1080) if part)
    with artifacts.atomic_path(dst) as tmp:
        run_ffmpeg(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}",
             "-i", str(video), "-an", "-vf", chain,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
             str(tmp)]
        )  # fmt: skip


def read_window(path: Path, first: int, last: int) -> dict[int, np.ndarray]:
    """The clip's frames in [first, last); only those stay in memory."""
    capture = cv2.VideoCapture(str(path))
    kept: dict[int, np.ndarray] = {}
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if first <= index < last:
            kept[index] = frame
        index += 1
        if index >= last:
            break
    capture.release()
    return kept


def frame_count(path: Path) -> int:
    capture = cv2.VideoCapture(str(path))
    count = 0
    while capture.grab():
        count += 1
    capture.release()
    return count


def sharpest(frames: Any, first: int, last: int) -> int:
    """The least blurry frame in [first, last)."""
    best, best_score = first, -1.0
    for index in range(first, max(first + 1, last)):
        gray = cv2.cvtColor(frames[index], cv2.COLOR_BGR2GRAY)
        score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if score > best_score:
            best, best_score = index, score
    return best


def work_area(boxes: list[Box], width: int, height: int) -> tuple[int, int, int, int]:
    """The region to track: around all candidates, at least MIN_AREA of the frame per side."""
    x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    w = min(width, max(x2 - x1 + 2 * AREA_MARGIN * width, MIN_AREA * width))
    h = min(height, max(y2 - y1 + 2 * AREA_MARGIN * height, MIN_AREA * height))
    w, h = int(w) // 2 * 2, int(h) // 2 * 2  # even sides for the video encoder
    left = int(min(max((x1 + x2) / 2 - w / 2, 0), width - w))
    top = int(min(max((y1 + y2) / 2 - h / 2, 0), height - h))
    return left, top, left + w, top + h


def cut_zoom(clip: Path, area: tuple[int, int, int, int], dst: Path) -> float:
    """The clip cropped to ``area`` and enlarged to ZOOM_SIDE; returns the enlargement."""
    x1, y1, x2, y2 = area
    scale = max(1.0, ZOOM_SIDE / max(x2 - x1, y2 - y1))
    w, h = int((x2 - x1) * scale) // 2 * 2, int((y2 - y1) * scale) // 2 * 2
    with artifacts.atomic_path(dst) as tmp:
        run_ffmpeg(
            ["ffmpeg", "-y", "-v", "error", "-i", str(clip),
             "-vf", f"crop={x2 - x1}:{y2 - y1}:{x1}:{y1},scale={w}:{h}:flags=bicubic",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
             str(tmp)]
        )  # fmt: skip
    return (w / (x2 - x1) + h / (y2 - y1)) / 2


def follow(
    client: Any,
    clip: Path,
    size: tuple[int, int],
    seeds: list[tuple[int, tuple]],
    area: tuple[int, int, int, int] | None = None,
    scale: float = 1.0,
) -> dict[int, dict[int, Box]]:
    """SAM video follows each (frame, box or point) from its frame: frame -> id -> box.

    Boxes and points are in clip pixels, and so are the answers.
    With ``area``, ``clip`` is the step clip cropped to it and enlarged by ``scale``: the
    prompts are moved into the zoomed clip and the answers moved back.
    """
    ox, oy = (area[0], area[1]) if area else (0, 0)
    zoomed = (round(size[0] * scale), round(size[1] * scale))
    if area:
        zoomed = (round((area[2] - area[0]) * scale), round((area[3] - area[1]) * scale))

    def moved(box: tuple) -> tuple:  # a box (l, t, r, b) or a point (x, y), into the zoom
        return tuple(int(round((v - (ox, oy)[i % 2]) * scale)) for i, v in enumerate(box))

    prompts = [(oid, frame, moved(box)) for oid, (frame, box) in enumerate(seeds, start=1)]
    tracks = client.segment_video(clip, boxes=prompts, size=zoomed)
    limit = MAX_SIDE * max(size)
    frames: dict[int, dict[int, Box]] = {}
    for frame in tracks:
        sx = zoomed[0] / frame.width if frame.width else 1.0
        sy = zoomed[1] / frame.height if frame.height else 1.0
        for obj in frame.objects:
            x1, y1, x2, y2 = obj.box
            box = (
                ox + x1 * sx / scale,
                oy + y1 * sy / scale,
                ox + x2 * sx / scale,
                oy + y2 * sy / scale,
            )
            if 0 < box[2] - box[0] <= limit and 0 < box[3] - box[1] <= limit:
                frames.setdefault(frame.frame, {})[obj.object_id] = box
    return frames


# 3. DECIDE ----------------------------------------------------------------------------------


def decide(
    frames: dict[int, dict[int, Box]], ids: list[int], count: int, adding: bool
) -> list[int]:
    """The ids seen steadily at their end of the step and clearly less at the other end."""
    window = max(1, round(count * SEED_SHARE))
    end = range(count - window, count)
    start = range(0, window)
    here, there = (end, start) if adding else (start, end)

    def share(oid: int, span: range) -> float:
        return sum(1 for index in span if oid in frames.get(index, {})) / len(span)

    return [
        oid
        for oid in ids
        if share(oid, here) >= STEADY and share(oid, here) - share(oid, there) >= CHANGE
    ]


def unique(frames: dict[int, dict[int, Box]], ids: list[int]) -> list[int]:
    """Merge an id that SAM follows onto the same fastener as an earlier id in most frames.

    The two masks are often two halves of one fastener (a bolt head and its washer), so the
    earlier id takes the union of both boxes, frame by frame.
    """
    kept: list[int] = []
    for oid in ids:
        twin = None
        for other in kept:
            both = [boxes for boxes in frames.values() if oid in boxes and other in boxes]
            if both and sum(same(b[oid], b[other]) for b in both) > len(both) / 2:
                twin = other
                break
        if twin is None:
            kept.append(oid)
            continue
        for boxes in frames.values():
            if oid in boxes:
                a = boxes.pop(oid)
                b = boxes.get(twin, a)
                boxes[twin] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
    return kept


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
    kinds: list[str],
    context: str,
    adding: bool,
    work: Path,
    duration_s: float,
    prefilter: str = "",
) -> tuple[Found, np.ndarray] | None:
    """Run the four stages on one step. Returns what was kept and the seed frame, or None."""
    end_s = min(step.end_s, duration_s) if duration_s else step.end_s
    if end_s - step.start_s <= 0:
        return None
    fps = clip_fps(end_s - step.start_s)
    work.mkdir(parents=True, exist_ok=True)
    clip = work / "clip.mp4"
    cut_step_clip(video, step.start_s, end_s, fps, clip, prefilter)
    count = frame_count(clip)
    if count < 3:
        return None
    window = max(1, round(count * SEED_SHARE))
    # only the frames of the step's end are kept in memory (start, when taking apart)
    frames = read_window(clip, count - window, count) if adding else read_window(clip, 0, window)
    height, width = next(iter(frames.values())).shape[:2]
    last = max(1, round(count * LAST_SHARE))
    if adding:  # the finished state: the end of the step, and its very last frames
        seeds = [sharpest(frames, count - window, count), sharpest(frames, count - last, count)]
    else:
        seeds = [sharpest(frames, 0, window), sharpest(frames, 0, last)]
    seeds = sorted(set(seeds))
    proposed: list[tuple[float, int, Box, str]] = []  # confidence, frame, box, kind
    for n, (seed, kind) in enumerate((seed, kind) for seed in seeds for kind in kinds):
        (work / f"try{n}").mkdir(exist_ok=True)
        for confidence, box in propose(client, frames[seed], kind, work / f"try{n}"):
            if not any(same(box, b) for _, f, b, _ in proposed if f == seed):
                proposed.append((confidence, seed, box, kind))
    found = Found(fps=fps, start_s=step.start_s, size=(width, height), seed=seeds[-1])
    if not proposed:
        return found, frames[found.seed]
    proposed = sorted(proposed, key=lambda item: -item[0])[:MAX_TRACKED]
    area = work_area([box for _, _, box, _ in proposed], width, height)
    if area == (0, 0, width, height):
        found.frames = follow(client, clip, (width, height), [(f, b) for _, f, b, _ in proposed])
    else:
        scale = cut_zoom(clip, area, work / "zoom.mp4")
        found.frames = follow(
            client, work / "zoom.mp4", (width, height),
            [(f, b) for _, f, b, _ in proposed], area, scale,
        )  # fmt: skip
    for oid, (_, frame, box, _) in enumerate(proposed, start=1):  # exactly where it was found
        found.frames.setdefault(frame, {})[oid] = box
    ids = unique(found.frames, list(range(1, len(proposed) + 1)))
    steady = decide(found.frames, ids, count, adding)
    here = range(count - window, count) if adding else range(0, window)
    kept = choose_tracks(client, model, frames, found.frames, steady, here, proposed, context)
    if step.screws and step.screws.count:  # never more than the analysis counted
        kept = kept[: step.screws.count]  # ids are in confidence order
    found.seed = max(  # drawn on the frame of its end that shows the most of them
        here, key=lambda i: (sum(oid in found.frames.get(i, {}) for oid in kept), i in seeds)
    )
    at_seed = {
        oid: found.frames[found.seed][oid]
        for oid in kept
        if oid in found.frames.get(found.seed, {})
    }
    found.kept = reading_order(at_seed, height)
    found.confidence = {oid: round(proposed[oid - 1][0], 2) for oid in found.kept}
    return found, frames[found.seed]


# 4. CHOOSE ----------------------------------------------------------------------------------


def choose_tracks(
    client: Any,
    model: str,
    frames: dict[int, np.ndarray],
    tracks: dict[int, dict[int, Box]],
    ids: list[int],
    here: range,
    proposed: list[tuple[float, int, Box, str]],
    context: str,
) -> list[int]:
    """Spark keeps, by number, the followed candidates that really are fasteners (VIEWS views)."""
    if not ids or not model or not hasattr(client, "respond"):
        return ids
    marks = []
    for oid in ids:
        seen = [i for i in here if oid in tracks.get(i, {})]
        picks = [seen[round(k * (len(seen) - 1) / max(1, VIEWS - 1))] for k in range(VIEWS)]
        views = []
        for index in dict.fromkeys(picks):
            image = frames[index]
            h, w = image.shape[:2]
            x1, y1, x2, y2 = tracks[index][oid]
            views.append((image, [x1 * 1000 / w, y1 * 1000 / h, x2 * 1000 / w, y2 * 1000 / h]))
        marks.append({"label": proposed[oid - 1][3], "views": views})
    checked = confirm_tracks(client, model, marks, context)
    return [oid for oid, mark in zip(ids, checked, strict=True) if mark["checked"]]
