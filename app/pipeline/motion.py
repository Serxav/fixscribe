"""Motion stage: SAM 3.1 follows the part through each step clip; fasteners come from perception.

SAM follows what the perception stage already proved: the box Spark pointed at and SAM cut out,
on the second it was found, propagated both ways through the clip. A step whose part was not
proven gets no clip, so a film never shows the wrong thing. Masks are smoothed
over time so the outline does not shake. The fasteners are not searched again here: the
perception stage already found, chose and followed them (``steps/NN_fasteners.json``), and
their tracks are drawn on this clip.

From the per-frame masks we render a clip with the same mark the site shows: the part's own shape
in orange with its name, following it, and every fastener with a numbered ring that moves with it.
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
from app.pipeline.analyze import guide_direction
from app.pipeline.fasteners import Found, load_found
from app.pipeline.ingest import run_ffmpeg
from app.pipeline.overlay import mark_part
from app.schemas import Identity, Motion, NormBox, PartHighlight, Perception, Plan, StepMotion

logger = logging.getLogger(__name__)

VERSION = "3"
MAX_STEPS = 12
FPS = 15
MAX_SECONDS = 5.0  # longer steps: 5 s around the part (SAM bills per frame)
WIDTH = 720  # long side of the working clip
HOLD_FRAMES = 4  # a mask SAM skipped on a frame is kept this many frames, then fades
SMOOTH = 0.6  # weight of this frame's mask against the previous one (removes jitter)
POP_FRAMES = 8  # a fastener that comes out leaves an expanding ring for this many frames
MAX_RING = 0.03  # ring radius at most this share of the frame's long side

RING = (10, 214, 255)  # yellow #ffd60a, BGR


class MotionError(Exception):
    """A step clip could not be tracked or rendered."""


@dataclass
class Track:
    """The masks of one concept over the frames of a clip, keyed by frame index."""

    masks: dict[int, np.ndarray]  # union of all objects of the concept, bool H x W
    objects: dict[int, dict[int, tuple[float, float, float, float]]]  # frame -> id -> box


def clip_window(start_s: float, end_s: float, around: float | None = None) -> tuple[float, float]:
    """The part of the step we track: all of it, or MAX_SECONDS around ``around`` or its middle."""
    length = max(0.0, end_s - start_s)
    if length <= MAX_SECONDS:
        return start_s, end_s
    middle = (start_s + end_s) / 2 if around is None else around
    first = min(max(start_s, middle - MAX_SECONDS / 2), end_s - MAX_SECONDS)
    return first, first + MAX_SECONDS


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
            x1, y1, x2, y2 = (int(round(v)) for v in boxes[obj.object_id])
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, max(x2, x1 + 1)), min(height, max(y2, y1 + 1))
            if obj.mask is None:  # no mask: use the box
                union[y1:y2, x1:x2] = True
                continue
            mask = np.asarray(obj.mask).astype(np.uint8)
            if mask.shape == (frame.height, frame.width):  # a full-frame mask
                full = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
                union |= full.astype(bool)
            else:  # SAM sends the mask of the box only: put it back where the box is
                local = cv2.resize(mask, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
                union[y1:y2, x1:x2] |= local.astype(bool)
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
    label: str = "",
) -> np.ndarray:
    """One frame with the marks the site shows; the video itself stays as it was filmed.

    `pops` are fasteners that just came out: (last box, 0..1 progress) -> an expanding ring.
    """
    out = mark_part(frame, part, label, part_alpha)
    if out is frame:
        out = frame.copy()

    for object_id, (x1, y1, x2, y2) in fasteners.items():
        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
        radius = int(min(max(9, 0.75 * max(x2 - x1, y2 - y1)), MAX_RING * max(out.shape[:2])))
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
        base = min(max(9, 0.75 * max(x2 - x1, y2 - y1)), MAX_RING * max(out.shape[:2]))
        radius = int(base * (1 + 2.2 * progress))
        overlay = out.copy()
        cv2.circle(overlay, (cx, cy), radius, RING, 3, cv2.LINE_AA)
        out = cv2.addWeighted(overlay, 1 - progress, out, progress, 0)
    return out


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


def has_audio(video: Path) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True,
    )  # fmt: skip
    return probe.returncode == 0 and bool(probe.stdout.strip())


def add_voice(video: Path, start_s: float, end_s: float, clip: Path) -> bool:
    """Put the technician's own words of this moment on the motion clip (if the video has sound).

    The best narrator is the person who did the repair: the film plays their real voice while
    taking apart, and only falls back to the device voice where there is none.
    """
    if not has_audio(video):
        return False
    with artifacts.atomic_path(clip) as tmp:
        run_ffmpeg(
            ["ffmpeg", "-y", "-v", "error", "-i", str(clip),
             "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}", "-i", str(video),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-shortest", "-movflags", "+faststart",
             str(tmp)]
        )  # fmt: skip
    return True


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


def follow(client: Any, clip: Path, size: tuple[int, int], boxes: list, frame: int, concept: str):
    """SAM video: follow the given boxes from `frame` (one id each), or the concept if none."""
    if boxes:
        prompts = [(object_id, frame, box) for object_id, box in enumerate(boxes, start=1)]
        return client.segment_video(clip, boxes=prompts, size=size)
    return client.segment_video(clip, concept)


def smoothed(track: Track | None, count: int, shape: tuple[int, int]) -> list[tuple]:
    """(mask, alpha) for every frame: held over skipped frames and smoothed over time."""
    out, previous = [], None
    for index in range(count):
        mask, alpha = held_mask(track, index, shape)
        current = mask.astype(np.float32)
        if previous is not None and alpha > 0:
            current = SMOOTH * current + (1 - SMOOTH) * previous
        previous = current if alpha > 0 else None
        out.append((current > 0.5, alpha))
    return out


def fastener_boxes(found: Found | None, t: float, size: tuple[int, int]) -> dict[int, tuple]:
    """Perception's kept fasteners at video time ``t``, scaled to this clip."""
    if found is None:
        return {}
    sx, sy = size[0] / found.size[0], size[1] / found.size[1]
    return {
        oid: (x1 * sx, y1 * sy, x2 * sx, y2 * sy)
        for oid, (x1, y1, x2, y2) in found.boxes_at(t).items()
    }


def gone_frames(found: Found, start: float, count: int) -> dict[int, tuple[int, tuple]]:
    """For each fastener taken out: the clip frame it was last seen on and its box there."""
    last: dict[int, tuple[int, tuple]] = {}
    for index in sorted(found.frames):
        for oid, box in found.frames[index].items():
            if oid in found.kept:
                last[oid] = (index, box)
    out = {}
    for oid, (index, box) in last.items():
        at = round((found.start_s + index / found.fps - start) * FPS)
        if 0 <= at < count - 1:
            out[oid] = (at, box)
    return out


def motion_for_step(
    job_dir: Path,
    client: Any,
    step,
    plan: Plan,
    direction: str = "disassemble",
    part: PartHighlight | None = None,
) -> StepMotion | None:
    found = load_found(job_dir, step.index)
    if part is None and not (found and found.kept):
        return None  # nothing proven to follow: the step opens on its photo
    concept = part.concept if part else ""
    start, end = clip_window(step.start_s, step.end_s, part.t_s if part else None)
    steps_dir = job_dir / "steps"
    source = steps_dir / f"{step.index:02d}_src.mp4"
    cut_source(job_dir / "video.mp4", start, min(end, plan.duration_s or end), source)
    frames = read_frames(source)
    height, width = frames[0].shape[:2]
    size = (width, height)
    part_track = Track(masks={}, objects={})
    if part is not None:
        box = part.box
        part_box = (
            int(box.x * width),
            int(box.y * height),
            int((box.x + box.w) * width),
            int((box.y + box.h) * height),
        )
        seed = min(len(frames) - 1, max(0, int(((part.t_s or start) - start) * FPS)))
        part_track = to_track(follow(client, source, size, [part_box], seed, concept), size)
    numbers = {oid: n for n, oid in enumerate(found.kept, start=1)} if found else {}
    gone = gone_frames(found, start, len(frames)) if found and direction != "assemble" else {}

    if not part_track.masks and not numbers:
        source.unlink(missing_ok=True)
        return None  # SAM followed nothing: the step opens on its photo, not on an empty film
    masks = smoothed(part_track, len(frames), (height, width))
    rendered = []
    for index, frame in enumerate(frames):
        part, alpha = masks[index]
        boxes = fastener_boxes(found, start + index / FPS, size)
        pops = [
            (box, (index - at) / POP_FRAMES)
            for oid, (at, box) in gone.items()
            if 0 < index - at <= POP_FRAMES
        ]
        rendered.append(
            render_frame(
                frame, part, alpha, boxes, numbers, index / max(1, len(frames) - 1), pops, concept
            )
        )
    clip = f"steps/{step.index:02d}_motion.mp4"
    clip_reverse = f"steps/{step.index:02d}_motion_rev.mp4"
    write_clip(rendered, job_dir / clip, reverse=job_dir / clip_reverse)
    voice = add_voice(job_dir / "video.mp4", start, start + len(frames) / FPS, job_dir / clip)

    motion = StepMotion(
        index=step.index,
        clip=clip,
        clip_reverse=clip_reverse,
        part=concept,
        fasteners_tracked=len(numbers),
        frames=len(frames),
        start_s=round(start, 3),
        end_s=round(start + len(frames) / FPS, 3),
        voice=voice,
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
    identity = artifacts.load_optional(job_dir, Identity)
    direction = guide_direction(identity.task if identity else None)
    perception = artifacts.load_optional(job_dir, Perception)
    proven = {item.index: item.part for item in perception.steps} if perception else {}
    result = Motion()
    for step in plan.steps[:MAX_STEPS]:
        try:
            motion = motion_for_step(job_dir, client, step, plan, direction, proven.get(step.index))
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
