"""Motion stage: SAM 3.1 tracks the part and the fasteners through each step clip.

SAM is used the way it works best: first FIND, then FOLLOW. On the sharpest frame of the step,
SAM image segmentation finds the part (text concept) and, on a zoomed crop around it, the
fasteners. Those boxes are then sent as prompts to SAM video tracking, so it follows exactly
those objects (one id each) instead of everything that looks alike. If finding fails we fall
back to tracking the text concept. Masks are smoothed over time so the outline does not shake.

From the per-frame masks we render a
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

VERSION = "2"
MAX_STEPS = 6
FPS = 15
MAX_SECONDS = 8.0  # longer steps: the middle 8 s (SAM bills per frame)
WIDTH = 720  # long side of the working clip
HOLD_FRAMES = 4  # a mask SAM skipped on a frame is kept this many frames, then fades
SMOOTH = 0.6  # weight of this frame's mask against the previous one (removes jitter)
SEED_MIN_CONFIDENCE = 0.3
MAX_FASTENERS = 15  # SAM video follows at most 16 prompted objects; 1 is the part
ZOOM_SIDE = 900  # fasteners are small: the crop around the part is upscaled to this side

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


def sharpest_frame(frames: list[np.ndarray], first: int, last: int) -> int:
    """The least blurry frame in [first, last) (variance of the Laplacian on a small copy)."""
    best, best_score = first, -1.0
    for index in range(first, max(first + 1, last)):
        gray = cv2.cvtColor(frames[index], cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (gray.shape[1] // 2, gray.shape[0] // 2))
        score = float(cv2.Laplacian(small, cv2.CV_64F).var())
        if score > best_score:
            best, best_score = index, score
    return best


def _write_png(image: np.ndarray, path: Path) -> Path:
    with artifacts.atomic_path(path) as tmp:
        if not cv2.imwrite(str(tmp), image):
            raise MotionError(f"cannot write {path.name}")
    return path


def _found(client: Any, image: np.ndarray, path: Path, concept: str) -> list[tuple]:
    """SAM image segmentation: [(confidence, (l, t, r, b) in `image` pixels), ...]."""
    detections, sent = client.segment(_write_png(image, path), concept)
    height, width = image.shape[:2]
    sx, sy = width / max(1, sent[0]), height / max(1, sent[1])
    found = []
    for item in detections:
        confidence = item.confidence if item.confidence is not None else 0.5
        if confidence < SEED_MIN_CONFIDENCE:
            continue
        x1, y1, x2, y2 = item.box
        box = (int(x1 * sx), int(y1 * sy), int(round(x2 * sx)), int(round(y2 * sy)))
        if box[2] > box[0] and box[3] > box[1]:
            found.append((confidence, box))
    return found


def seed_part(client: Any, frame: np.ndarray, concept: str, work: Path) -> tuple | None:
    """The single best box of the part on the seed frame (most confident, then largest)."""
    found = _found(client, frame, work / "seed.png", concept)
    if not found:
        return None
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])  # noqa: E731
    return max(found, key=lambda item: (round(item[0], 2), area(item[1])))[1]


def seed_fasteners(
    client: Any, frame: np.ndarray, around: tuple | None, fastener: str, work: Path
) -> list[tuple]:
    """Fastener boxes on a zoomed crop around the part (whole frame if no part)."""
    height, width = frame.shape[:2]
    if around is None:
        x1, y1, x2, y2 = 0, 0, width, height
    else:
        cx, cy = (around[0] + around[2]) / 2, (around[1] + around[3]) / 2
        half_w, half_h = (around[2] - around[0]) * 0.65, (around[3] - around[1]) * 0.65
        x1, y1 = int(max(0, cx - half_w)), int(max(0, cy - half_h))
        x2, y2 = int(min(width, cx + half_w)), int(min(height, cy + half_h))
    crop = frame[y1:y2, x1:x2]
    scale = max(1.0, ZOOM_SIDE / max(crop.shape[:2]))
    zoomed = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    found = _found(client, zoomed, work / "seed_fasteners.png", fastener)
    boxes = []
    for _, (left, top, right, bottom) in sorted(found, key=lambda item: -item[0]):
        box = (
            x1 + int(left / scale),
            y1 + int(top / scale),
            x1 + int(right / scale),
            y1 + int(bottom / scale),
        )
        if all(_overlap(box, other) < 0.5 for other in boxes):
            boxes.append(box)
    return boxes[:MAX_FASTENERS]


def _overlap(a: tuple, b: tuple) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


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

    size = (width, height)
    work = steps_dir / f"{step.index:02d}_work"
    seed = sharpest_frame(frames, 0, max(1, len(frames) // 2))
    part_box = seed_part(client, frames[seed], concept, work)
    part_track = to_track(
        follow(client, source, size, [part_box] if part_box else [], seed, concept), size
    )
    screw_track = None
    if step.screws and step.screws.count:
        # Fasteners are seeded on the first frame: they are all still in place there.
        around = part_box or _track_box(part_track)
        screws = seed_fasteners(client, frames[0], around, fastener, work)
        screw_track = to_track(follow(client, source, size, screws, 0, fastener), size)
    removed = removed_fasteners(screw_track, len(frames))
    numbers = fastener_numbers(screw_track, set(removed))
    seen_last = last_boxes(screw_track)
    pop_frames = 8

    masks = smoothed(part_track, len(frames), (height, width))
    rendered = []
    for index, frame in enumerate(frames):
        part, alpha = masks[index]
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
    voice = add_voice(job_dir / "video.mp4", start, start + len(frames) / FPS, job_dir / clip)

    motion = StepMotion(
        index=step.index,
        clip=clip,
        clip_reverse=clip_reverse,
        part=concept,
        fasteners_tracked=len(numbers),
        frames=len(frames) * (2 if screw_track is not None else 1),
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
    for leftover in work.glob("*") if work.is_dir() else []:
        leftover.unlink(missing_ok=True)
    if work.is_dir():
        work.rmdir()
    return motion


def _track_box(track: Track) -> tuple | None:
    """The box around the part where SAM saw it largest (seed for the fastener search)."""
    best = best_frame(track)
    if best is None:
        return None
    ys, xs = np.nonzero(track.masks[best])
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


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
