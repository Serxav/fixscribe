"""Motion stage: SAM 3.1 tracks the part and the fasteners through each step clip.

For every step with a target part, a short clip of the step goes to SAM 3.1 video tracking twice
(the part, then the fastener kind of the domain). From the per-frame masks we render a
"cinematic" clip: the scene dims and loses colour, the part stays in full colour with a soft glow
and a crisp outline that follows it, and every fastener gets a numbered ring that moves with it.
We also cut the part out along its mask (transparent PNG) and keep its outline as an SVG path, so
the web page can lift the real shape of the part in 3D instead of a rectangle.
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import artifacts
from app.config import Settings
from app.meta_client import BudgetExceeded, make_client
from app.pipeline.ingest import run_ffmpeg
from app.pipeline.perception import fastener_concept, part_concept
from app.schemas import Motion, NormBox, Plan, StepMotion

logger = logging.getLogger(__name__)

VERSION = "1"
MAX_STEPS = 6
FPS = 15
MAX_SECONDS = 8.0  # longer steps: the middle 8 s (SAM bills per frame)
WIDTH = 720  # long side of the working clip
HOLD_FRAMES = 4  # a mask SAM skipped on a frame is kept this many frames, then fades

ACCENT = (255, 132, 10)  # BGR of #0a84ff
OUTLINE = (255, 214, 120)  # light cyan-blue, BGR
RING = (10, 214, 255)  # yellow #ffd60a, BGR


class MotionError(Exception):
    """A step clip could not be tracked or rendered."""


@dataclass
class Track:
    """The masks of one concept over the frames of a clip, keyed by frame index."""

    masks: dict[int, np.ndarray]  # union of all objects of the concept, bool H x W
    objects: dict[int, dict[int, tuple[float, float, float, float]]]  # frame -> id -> box


def clip_window(start_s: float, end_s: float) -> tuple[float, float]:
    """The part of the step we track: all of it, or its middle MAX_SECONDS."""
    length = max(0.0, end_s - start_s)
    if length <= MAX_SECONDS:
        return start_s, end_s
    middle = (start_s + end_s) / 2
    return middle - MAX_SECONDS / 2, middle + MAX_SECONDS / 2


def cut_source(video: Path, start_s: float, end_s: float, dst: Path) -> None:
    """A small constant-rate clip of the step: the exact frames SAM sees and we draw on."""
    scale = f"scale='if(gt(iw,ih),{WIDTH},-2)':'if(gt(iw,ih),-2,{WIDTH})'"
    with artifacts.atomic_path(dst) as tmp:
        run_ffmpeg(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}",
             "-i", str(video), "-an", "-vf", f"fps={FPS},{scale}",
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
    if not frames:
        raise MotionError(f"no frames in {path.name}")
    return frames


def to_track(frames: list[Any], size: tuple[int, int]) -> Track:
    """FrameTrack list from MetaClient.segment_video -> one union mask per frame."""
    width, height = size
    masks: dict[int, np.ndarray] = {}
    objects: dict[int, dict[int, tuple[float, float, float, float]]] = {}
    for frame in frames:
        union = np.zeros((height, width), dtype=bool)
        boxes = {}
        for obj in frame.objects:
            boxes[obj.object_id] = _scale_box(obj.box, (frame.width, frame.height), size)
            if obj.mask is not None:
                mask = np.asarray(obj.mask).astype(np.uint8)
                if mask.shape != (height, width):
                    mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
                union |= mask.astype(bool)
            else:  # no mask: use the box
                x1, y1, x2, y2 = (int(round(v)) for v in boxes[obj.object_id])
                union[max(0, y1) : max(0, y2), max(0, x1) : max(0, x2)] = True
        masks[frame.frame] = union
        objects[frame.frame] = boxes
    return Track(masks=masks, objects=objects)


def _scale_box(box, source: tuple[int, int], target: tuple[int, int]):
    sx = target[0] / source[0] if source[0] else 1.0
    sy = target[1] / source[1] if source[1] else 1.0
    x1, y1, x2, y2 = box
    return (x1 * sx, y1 * sy, x2 * sx, y2 * sy)


def held_mask(track: Track | None, index: int, shape: tuple[int, int]) -> tuple[np.ndarray, float]:
    """The mask for a frame and how strongly to show it (SAM may skip frames: hold, then fade)."""
    empty = np.zeros(shape, dtype=bool)
    if track is None:
        return empty, 0.0
    for back in range(HOLD_FRAMES + 1):
        mask = track.masks.get(index - back)
        if mask is not None and mask.any():
            return mask, 1.0 - back / (HOLD_FRAMES + 1)
    return empty, 0.0


def render_frame(
    frame: np.ndarray,
    part: np.ndarray,
    part_alpha: float,
    fasteners: dict[int, tuple[float, float, float, float]],
    numbers: dict[int, int],
    t: float,
    pops: list[tuple[tuple[float, float, float, float], float]] = (),
) -> np.ndarray:
    """One cinematic frame. `t` is 0..1 along the clip (for the intro and the glow pulse).

    `pops` are fasteners that just came out: (last box, 0..1 progress) -> an expanding ring.
    """
    intro = min(1.0, t * 6)  # the first ~15 % of the clip eases from normal to styled
    gray = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    dim = cv2.addWeighted(frame, 0.35, gray, 0.65, 0) * 0.42
    dim = dim + np.array([18, 10, 4], dtype=np.float32)  # a cool blue cast in the shadows
    styled = dim.astype(np.float32)

    if part_alpha > 0 and part.any():
        soft = cv2.GaussianBlur(part.astype(np.float32), (0, 0), 2.0)[..., None] * part_alpha
        lit = np.clip(frame.astype(np.float32) * 1.08 + 6, 0, 255)
        styled = styled * (1 - soft) + lit * soft
        ring = cv2.dilate(part.astype(np.uint8), np.ones((9, 9), np.uint8)) - part.astype(np.uint8)
        pulse = 0.75 + 0.25 * np.sin(t * np.pi * 4)
        glow = cv2.GaussianBlur(ring.astype(np.float32), (0, 0), 9.0)[..., None]
        styled = styled + glow * np.array(ACCENT, dtype=np.float32) * 1.6 * pulse * part_alpha

    out = frame.astype(np.float32) * (1 - intro) + styled * intro
    out = np.clip(out, 0, 255).astype(np.uint8)

    if part_alpha > 0 and part.any():
        contours, _ = cv2.findContours(
            part.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        overlay = out.copy()
        cv2.drawContours(overlay, contours, -1, OUTLINE, 2, cv2.LINE_AA)
        out = cv2.addWeighted(overlay, part_alpha * intro, out, 1 - part_alpha * intro, 0)

    for object_id, (x1, y1, x2, y2) in fasteners.items():
        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
        radius = int(max(9, 0.75 * max(x2 - x1, y2 - y1)))
        if object_id not in numbers:  # stays in place during this step: a faint ring only
            cv2.circle(out, (cx, cy), radius, (235, 235, 235), 1, cv2.LINE_AA)
            continue
        cv2.circle(out, (cx, cy), radius + 3, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.circle(out, (cx, cy), radius, RING, 2, cv2.LINE_AA)
        badge = (cx + radius + 4, cy - radius - 4)
        cv2.circle(out, badge, 11, RING, -1, cv2.LINE_AA)
        label = str(numbers.get(object_id, ""))
        size = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 0.5, 1)[0]
        cv2.putText(out, label, (badge[0] - size[0] // 2, badge[1] + size[1] // 2),
                    cv2.FONT_HERSHEY_DUPLEX, 0.5, (20, 20, 20), 1, cv2.LINE_AA)  # fmt: skip
    for (x1, y1, x2, y2), progress in pops:
        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
        radius = int(max(9, 0.75 * max(x2 - x1, y2 - y1)) * (1 + 2.2 * progress))
        overlay = out.copy()
        cv2.circle(overlay, (cx, cy), radius, RING, 3, cv2.LINE_AA)
        out = cv2.addWeighted(overlay, 1 - progress, out, progress, 0)
    return out


def removed_fasteners(track: Track | None, frame_count: int) -> dict[int, int]:
    """The fasteners taken out during the clip (seen, then gone before the end).

    Returns {object_id: last frame seen}. A fastener still there at the end was not removed in
    this step, so it is only drawn faintly.
    """
    if track is None or not track.objects:
        return {}
    last: dict[int, int] = {}
    for index, boxes in track.objects.items():
        for object_id in boxes:
            last[object_id] = max(index, last.get(object_id, -1))
    end = max(frame_count - 1, max(track.objects))
    return {oid: seen for oid, seen in last.items() if seen < end - HOLD_FRAMES}


def fastener_numbers(track: Track | None, only: set[int] | None = None) -> dict[int, int]:
    """Number fasteners 1, 2, 3... in reading order of where they first appear."""
    if track is None:
        return {}
    first: dict[int, tuple[float, float]] = {}
    for index in sorted(track.objects):
        for object_id, (x1, y1, x2, y2) in track.objects[index].items():
            if only is None or object_id in only:
                first.setdefault(object_id, ((y1 + y2) / 2, (x1 + x2) / 2))
    ordered = sorted(first, key=lambda oid: (round(first[oid][0] / 40), first[oid][1]))
    return {oid: n for n, oid in enumerate(ordered, start=1)}


def last_boxes(track: Track | None) -> dict[int, tuple[float, float, float, float]]:
    """Where each fastener was last seen (for the 'pop' when it comes out)."""
    found: dict[int, tuple[float, float, float, float]] = {}
    if track is not None:
        for index in sorted(track.objects):
            found.update(track.objects[index])
    return found


def write_clip(frames: list[np.ndarray], dst: Path, reverse: Path | None = None) -> None:
    height, width = frames[0].shape[:2]
    with artifacts.atomic_path(dst) as tmp:
        process = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{width}x{height}", "-r", str(FPS), "-i", "-",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(tmp)],
            stdin=subprocess.PIPE,
        )  # fmt: skip
        assert process.stdin is not None
        for frame in frames:
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise MotionError(f"ffmpeg could not write {dst.name}")
    if reverse is not None:
        with artifacts.atomic_path(reverse) as tmp:
            run_ffmpeg(["ffmpeg", "-y", "-v", "error", "-i", str(dst), "-vf", "reverse",
                        "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(tmp)])  # fmt: skip


def best_frame(track: Track) -> int | None:
    """The frame where the part is seen largest (the cut-out is taken there)."""
    sizes = {index: int(mask.sum()) for index, mask in track.masks.items()}
    return max(sizes, key=sizes.get) if sizes and max(sizes.values()) > 0 else None


def cutout(frame: np.ndarray, mask: np.ndarray, dst: Path) -> NormBox:
    """Save the part alone (transparent PNG, soft edge) and return where it sits on the frame."""
    ys, xs = np.nonzero(mask)
    x1, x2, y1, y2 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 1.2)
    rgba = np.dstack([frame, (alpha * 255).astype(np.uint8)])[y1:y2, x1:x2]
    with artifacts.atomic_path(dst) as tmp:
        if not cv2.imwrite(str(tmp), rgba):
            raise MotionError(f"cannot write {dst.name}")
    height, width = mask.shape
    return NormBox(x=x1 / width, y=y1 / height, w=(x2 - x1) / width, h=(y2 - y1) / height)


def outline_path(mask: np.ndarray) -> str:
    """The part outline as an SVG path in a 0..1000 square (simplified, largest shapes first)."""
    height, width = mask.shape
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:3]
    parts = []
    for contour in contours:
        epsilon = 0.004 * cv2.arcLength(contour, True)
        points = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        if len(points) < 3:
            continue
        coords = [f"{x * 1000 / width:.0f} {y * 1000 / height:.0f}" for x, y in points]
        parts.append("M" + " L".join(coords) + " Z")
    return " ".join(parts)


def motion_for_step(
    job_dir: Path, client: Any, step, plan: Plan, fastener: str
) -> StepMotion | None:
    concept = part_concept(step.target_part, step.removes)
    if concept is None:
        return None
    start, end = clip_window(step.start_s, step.end_s)
    steps_dir = job_dir / "steps"
    source = steps_dir / f"{step.index:02d}_src.mp4"
    cut_source(job_dir / "video.mp4", start, min(end, plan.duration_s or end), source)
    frames = read_frames(source)
    height, width = frames[0].shape[:2]

    part_track = to_track(client.segment_video(source, concept), (width, height))
    screw_track = None
    if step.screws and step.screws.count:
        screw_track = to_track(client.segment_video(source, fastener), (width, height))
    removed = removed_fasteners(screw_track, len(frames))
    numbers = fastener_numbers(screw_track, set(removed))
    seen_last = last_boxes(screw_track)
    pop_frames = 8

    rendered = []
    for index, frame in enumerate(frames):
        part, alpha = held_mask(part_track, index, (height, width))
        boxes = screw_track.objects.get(index, {}) if screw_track else {}
        pops = [
            (seen_last[oid], (index - gone) / pop_frames)
            for oid, gone in removed.items()
            if 0 < index - gone <= pop_frames
        ]
        rendered.append(
            render_frame(frame, part, alpha, boxes, numbers, index / max(1, len(frames) - 1), pops)
        )
    clip = f"steps/{step.index:02d}_motion.mp4"
    clip_reverse = f"steps/{step.index:02d}_motion_rev.mp4"
    write_clip(rendered, job_dir / clip, reverse=job_dir / clip_reverse)

    motion = StepMotion(
        index=step.index,
        clip=clip,
        clip_reverse=clip_reverse,
        part=concept,
        fasteners_tracked=len(numbers),
        frames=len(frames) * (2 if screw_track is not None else 1),
    )
    best = best_frame(part_track)
    if best is not None and best < len(frames):
        mask = part_track.masks[best]
        motion.cutout = f"steps/{step.index:02d}_cutout.png"
        motion.cutout_box = cutout(frames[best], mask, job_dir / motion.cutout)
        motion.outline = outline_path(mask)
    source.unlink(missing_ok=True)
    return motion


def run(job_dir: Path, settings: Settings, client: Any = None) -> Motion:
    plan = artifacts.load(job_dir, Plan)
    if client is None:
        client = make_client(settings, job_dir=job_dir)
    fastener = fastener_concept(job_dir)
    result = Motion()
    for step in plan.steps[:MAX_STEPS]:
        try:
            motion = motion_for_step(job_dir, client, step, plan, fastener)
        except BudgetExceeded:
            result.notes.append("SAM budget reached: later steps have no motion clip.")
            break
        except Exception as exc:  # one bad step never stops the others
            logger.warning("motion failed for step %d: %s", step.index, exc)
            result.notes.append(f"Step {step.index}: no motion clip ({exc}).")
            continue
        if motion is not None:
            result.steps.append(motion)
    artifacts.save(job_dir, result)
    return result
