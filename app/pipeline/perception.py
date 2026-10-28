"""Perception stage: SAM part highlight and before/after screw ledger.

For each planned step SAM 3.1 looks for the part on the keyframe still and,
when the step removes screws, for screws on stills just before and just
after the step. Screws are searched on native-resolution crops around the
part, upscaled so a few-pixel screw becomes visible. A screw present before
and missing after was removed in that step and joins the screw ledger
(in an assembly the other way round: missing before, present after, means it
was put in). When the client can ask Muse Spark, every screw candidate is
checked again on a zoomed contact sheet, so holes, wood grain and reflections
are dropped, and a part SAM cannot find by name is pointed at by Spark.
Never more fasteners than the analysis counted are kept (the most confident
first): a fastener hidden in the wood is counted, never invented.
Everything is saved in ``perception.json``; this stage writes no other
artifact.
"""

import math
import statistics
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import artifacts
from app.config import Settings
from app.domains import profile_for
from app.meta_client import BudgetExceeded, Detection, make_client
from app.pipeline.frames import hand_fraction, roi_sharpness
from app.pipeline.ingest import find_original
from app.pipeline.media import extract_still
from app.pipeline.overlay import draw_part, draw_screws, save_jpeg
from app.pipeline.verify import MAX_TILES, confirm
from app.schemas import (
    Frames,
    Identity,
    IngestInfo,
    NormBox,
    PartHighlight,
    Perception,
    Plan,
    ScrewRecord,
    Step,
    StepPerception,
)
from app.text import ARTICLES, plural

MAX_STEPS = 12
BEFORE_S = 0.5
AFTER_S = 0.5
ROI_GROW = 1.6
MIN_ROI = 0.5  # never search fasteners in less than half the frame: a tiny part is no area
MIN_CROP_SIDE = 900
MIN_CONFIDENCE = 0.3
NMS_IOU = 0.5
SAME_SCREW = 0.04
STILL_TRIES = (-0.3, 0.0, 0.3)  # seconds around a before/after time; the clearest frame wins

_BUDGET_NOTE = "SAM budget reached."


def fastener_concept(job_dir: Path) -> str:
    """The SAM fastener word for this job: the profile kind, or "screw"."""
    identity = artifacts.load_optional(job_dir, Identity)
    if identity is None:
        return "screw"
    return profile_for(identity.category).fastener_kind


FASTENER_WORDS = ("screw", "bolt", "nut", "dowel", "pin", "washer", "clip", "rivet", "peg", "stud")


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


MAX_CONCEPT_TRIES = 3  # SAM calls spent looking for the part of one step


def part_concepts(step: Step) -> list[str]:
    """The words to ask SAM for the part, best first, without repeats.

    Spark's `sam_concept` (a plain noun chosen to be visible) comes first; then the part names;
    then their last word alone, because SAM finds "leg" when it cannot find "leg frame c".
    """
    names = [step.sam_concept, step.target_part, *(step.removes or [])]
    found: list[str] = []
    for name in names:
        phrase = _clean_phrase(name)
        if phrase is None:
            continue
        for candidate in (phrase, phrase.split()[-1]):
            if candidate not in found and (len(candidate) > 2 and not candidate.isdigit()):
                found.append(candidate)
    return found[:MAX_CONCEPT_TRIES]


def part_concept(target_part: str | None, removes: list[str]) -> str | None:
    """One short noun phrase for SAM, from the target part or what it removes."""
    concept = _clean_phrase(target_part)
    if concept is not None:
        return concept
    for item in removes or []:
        concept = _clean_phrase(item)
        if concept is not None:
            return concept
    return None


def _screw_count(step: Step) -> int:
    return step.screws.count if step.screws else 0


def _confidence_ok(detection: Detection) -> bool:
    return detection.confidence is None or detection.confidence >= MIN_CONFIDENCE


def _confidence_value(detection: Detection) -> float:
    return detection.confidence if detection.confidence is not None else 0.0


def _norm_box(box: tuple[float, float, float, float], size: tuple[int, int]) -> NormBox | None:
    width, height = size
    if width <= 0 or height <= 0:
        return None
    left, top, right, bottom = box
    x = min(1.0, max(0.0, left / width))
    y = min(1.0, max(0.0, top / height))
    x2 = min(1.0, max(0.0, right / width))
    y2 = min(1.0, max(0.0, bottom / height))
    if x2 <= x or y2 <= y:
        return None
    return NormBox(x=x, y=y, w=x2 - x, h=y2 - y)


def _iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    inter = (right - left) * (bottom - top)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _nms(detections: list[Detection]) -> list[Detection]:
    """Keep the most confident detection of each overlapping group."""
    kept: list[Detection] = []
    for detection in sorted(detections, key=_confidence_value, reverse=True):
        if all(_iou(detection.box, other.box) <= NMS_IOU for other in kept):
            kept.append(detection)
    return kept


def roi_of(part: PartHighlight | None) -> tuple[float, float, float, float]:
    """The part box grown by ``ROI_GROW`` as ``(x, y, w, h)``, or the whole frame."""
    if part is None:
        return (0.0, 0.0, 1.0, 1.0)
    box = part.box
    grown_w = min(1.0, max(box.w * ROI_GROW, MIN_ROI))
    grown_h = min(1.0, max(box.h * ROI_GROW, MIN_ROI))
    centre_x = box.x + box.w / 2
    centre_y = box.y + box.h / 2
    x = min(max(centre_x - grown_w / 2, 0.0), 1.0 - grown_w)
    y = min(max(centre_y - grown_h / 2, 0.0), 1.0 - grown_h)
    return (x, y, grown_w, grown_h)


def _read_image(path: Path) -> Any:
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"cannot read image: {path}")
    return image


_ALIGN_MAX_SIDE = 1280
_MIN_INLIERS = 15
_ALIGN_FAILED_NOTE = "Camera moved too much to verify the screws."


def _align_failed_note(fastener: str) -> str:
    if fastener == "screw":
        return _ALIGN_FAILED_NOTE
    return f"Camera moved too much to verify the {plural(fastener)}."


def _gray_small(image: Any) -> tuple[Any, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]
    longest = max(width, height)
    scale = min(1.0, _ALIGN_MAX_SIDE / longest) if longest > 0 else 1.0
    if scale >= 1.0:
        return gray, scale
    small = cv2.resize(
        gray,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )
    return small, scale


def align_after_to_before(before_img: Any, after_img: Any) -> np.ndarray | None:
    """Similarity transform mapping after-still pixels into before-still pixels.

    Returns the full-size 2x3 matrix, or ``None`` when there are fewer than
    15 RANSAC inliers (too little texture to trust the alignment).
    """
    if before_img is None or after_img is None:
        return None
    before_small, before_scale = _gray_small(before_img)
    after_small, after_scale = _gray_small(after_img)
    orb = cv2.ORB_create(2000)
    before_kp, before_des = orb.detectAndCompute(before_small, None)
    after_kp, after_des = orb.detectAndCompute(after_small, None)
    if before_des is None or after_des is None:
        return None
    if len(before_kp) < _MIN_INLIERS or len(after_kp) < _MIN_INLIERS:
        return None
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(after_des, before_des)
    if len(matches) < _MIN_INLIERS:
        return None
    src = np.float32([after_kp[match.queryIdx].pt for match in matches]).reshape(-1, 1, 2)
    dst = np.float32([before_kp[match.trainIdx].pt for match in matches]).reshape(-1, 1, 2)
    matrix, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC)
    if matrix is None or inliers is None or int(inliers.sum()) < _MIN_INLIERS:
        return None
    full = matrix.astype(np.float64, copy=True)
    full[:, :2] *= after_scale / before_scale
    full[:, 2] /= before_scale
    return full


def _moved(box: NormBox, matrix: np.ndarray, source: Any, target: Any) -> NormBox:
    """A box on ``source`` moved by the 2x3 pixel ``matrix`` onto ``target`` (same size kept)."""
    src_h, src_w = source.shape[:2]
    dst_h, dst_w = target.shape[:2]
    cx, cy = (box.x + box.w / 2) * src_w, (box.y + box.h / 2) * src_h
    x, y = matrix @ np.array([cx, cy, 1.0])
    w, h = box.w * src_w / dst_w, box.h * src_h / dst_h
    return NormBox(
        x=min(max(x / dst_w - w / 2, 0.0), 1.0 - w),
        y=min(max(y / dst_h - h / 2, 0.0), 1.0 - h),
        w=w,
        h=h,
    )


def _write_png_atomic(image: Any, path: Path) -> None:
    with artifacts.atomic_path(path) as tmp:
        if not cv2.imwrite(str(tmp), image):
            raise OSError(f"cannot write image: {path}")


def _crop_upscaled(image: Any, roi: tuple[float, float, float, float]) -> Any:
    height, width = image.shape[:2]
    roi_x, roi_y, roi_w, roi_h = roi
    x1 = min(width - 1, max(0, int(round(roi_x * width))))
    y1 = min(height - 1, max(0, int(round(roi_y * height))))
    x2 = min(width, max(x1 + 1, int(round((roi_x + roi_w) * width))))
    y2 = min(height, max(y1 + 1, int(round((roi_y + roi_h) * height))))
    crop = image[y1:y2, x1:x2]
    crop_h, crop_w = crop.shape[:2]
    shortest = min(crop_w, crop_h)
    if shortest < MIN_CROP_SIDE:
        factor = MIN_CROP_SIDE / shortest
        crop = cv2.resize(
            crop,
            (max(1, int(round(crop_w * factor))), max(1, int(round(crop_h * factor)))),
            interpolation=cv2.INTER_CUBIC,
        )
    return crop


def _segment(client: Any, sp: StepPerception, path: Path, concept: str, **kwargs: Any) -> Any:
    sp.sam_calls += 1
    return client.segment(path, concept, **kwargs)


def _map_to_still(
    detection: Detection, sent_size: tuple[int, int], roi: tuple[float, float, float, float]
) -> NormBox | None:
    sent_w, sent_h = sent_size
    if sent_w <= 0 or sent_h <= 0:
        return None
    left, top, right, bottom = detection.box
    roi_x, roi_y, roi_w, roi_h = roi
    x = roi_x + (left / sent_w) * roi_w
    y = roi_y + (top / sent_h) * roi_h
    x2 = roi_x + (right / sent_w) * roi_w
    y2 = roi_y + (bottom / sent_h) * roi_h
    x = min(1.0, max(0.0, x))
    y = min(1.0, max(0.0, y))
    x2 = min(1.0, max(0.0, x2))
    y2 = min(1.0, max(0.0, y2))
    if x2 <= x or y2 <= y:
        return None
    return NormBox(x=x, y=y, w=x2 - x, h=y2 - y)


def fasteners_on_still(
    client: Any,
    sp: StepPerception,
    still_path: Path,
    roi: tuple[float, float, float, float],
    image: Any = None,
    fastener: str = "screw",
) -> list[tuple[NormBox, float | None]]:
    if image is None:
        image = _read_image(still_path)
    crop = _crop_upscaled(image, roi)
    crop_path = still_path.with_name(f"{still_path.stem}_crop.png")
    _write_png_atomic(crop, crop_path)
    detections, sent_size = _segment(client, sp, crop_path, fastener)
    if not detections and " " in fastener:  # SAM knows "bolt" better than "allen bolt"
        detections, sent_size = _segment(client, sp, crop_path, fastener.split()[-1])
    kept = _nms([item for item in detections if _confidence_ok(item)])
    found: list[tuple[NormBox, float | None]] = []
    for detection in kept:
        box = _map_to_still(detection, sent_size, roi)
        if box is not None:
            found.append((box, detection.confidence))
    return found


def pointed_fasteners(
    client: Any,
    crop_path: Path,
    roi: tuple[float, float, float, float],
    fastener: str,
    context: str,
    found: list[tuple[NormBox, float | None]],
) -> list[tuple[NormBox, float | None]]:
    """Add the fasteners Spark points at on the same crop that SAM missed."""
    if not hasattr(client, "ground") or not crop_path.is_file():
        return found
    roi_x, roi_y, roi_w, roi_h = roi
    out = list(found)
    for item in client.ground(crop_path, f"each {fastener}", context=context, max_boxes=16):
        x1, y1, x2, y2 = item.box
        if x2 <= x1 or y2 <= y1:
            continue
        box = NormBox(
            x=roi_x + x1 / 1000 * roi_w,
            y=roi_y + y1 / 1000 * roi_h,
            w=(x2 - x1) / 1000 * roi_w,
            h=(y2 - y1) / 1000 * roi_h,
        )
        corners = (box.x, box.y, box.x + box.w, box.y + box.h)
        if all(_iou(corners, (b.x, b.y, b.x + b.w, b.y + b.h)) <= 0.3 for b, _ in out):
            out.append((box, 0.5))
    return out


def checked_fasteners(
    client: Any,
    image: Any,
    found: list[tuple[NormBox, float | None]],
    model: str,
    context: str,
    fastener: str,
) -> list[tuple[NormBox, float | None]]:
    """Spark's second look at every candidate; kept as is when the client cannot ask Spark."""
    if not found or not model or not hasattr(client, "respond"):
        return found
    found = sorted(found, key=lambda item: -(item[1] or 0.0))[:MAX_TILES]
    marks = [
        {
            "label": fastener,
            "cut_box": [
                round(box.x * 1000),
                round(box.y * 1000),
                round((box.x + box.w) * 1000),
                round((box.y + box.h) * 1000),
            ],
        }
        for box, _ in found
    ]
    checked = confirm(client, model, image, marks, context)
    return [item for item, mark in zip(found, checked, strict=True) if mark["checked"]]


def _pointed_part(client: Any, path: Path, concept: str, context: str) -> PartHighlight | None:
    """Spark points at the part SAM could not find by name (0..1000 grid of the still)."""
    if not hasattr(client, "ground"):
        return None
    boxes = client.ground(path, concept, context=context, max_boxes=1)
    if not boxes:
        return None
    x1, y1, x2, y2 = boxes[0].box
    if x2 <= x1 or y2 <= y1:
        return None
    return PartHighlight(
        concept=concept,
        box=NormBox(x=x1 / 1000, y=y1 / 1000, w=(x2 - x1) / 1000, h=(y2 - y1) / 1000),
        confidence=None,
    )


def _centre(box: NormBox) -> tuple[float, float]:
    return (box.x + box.w / 2, box.y + box.h / 2)


def _reading_order(
    items: list[tuple[NormBox, float | None]],
) -> list[tuple[NormBox, float | None]]:
    """Top-to-bottom rows, then left-to-right inside each row."""
    if not items:
        return []
    tolerance = max(statistics.median([box.h for box, _ in items]) * 0.5, 0.005)
    rows: list[list[tuple[NormBox, float | None]]] = []
    row_centres: list[float] = []
    for item in sorted(items, key=lambda entry: (_centre(entry[0])[1], _centre(entry[0])[0])):
        centre_y = _centre(item[0])[1]
        if rows and abs(centre_y - row_centres[-1]) <= tolerance:
            rows[-1].append(item)
            row_centres[-1] = statistics.fmean([_centre(entry[0])[1] for entry in rows[-1]])
        else:
            rows.append([item])
            row_centres.append(centre_y)
    ordered: list[tuple[NormBox, float | None]] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda entry: _centre(entry[0])[0]))
    return ordered


def _still_at(
    job_dir: Path,
    ingest: IngestInfo | None,
    t: float,
    dst: Path,
    duration_s: float,
) -> Path:
    if dst.is_file():
        return dst
    if ingest is None or ingest.source is None:
        raise ValueError("missing ingest.json source for still extraction")
    original = find_original(job_dir)
    clamped = min(max(t, 0.0), duration_s)
    extract_still(original, ingest.source, clamped, dst)
    return dst


def _clear_still_at(
    job_dir: Path,
    ingest: IngestInfo | None,
    t: float,
    dst: Path,
    duration_s: float,
) -> Path:
    """The sharpest frame with the least hand in it, a few tenths of a second around ``t``."""
    if dst.is_file() or ingest is None or ingest.source is None:
        return _still_at(job_dir, ingest, t, dst, duration_s)
    best: tuple[float, Path] | None = None
    tries: list[Path] = []
    for n, shift in enumerate(STILL_TRIES):
        path = dst.with_name(f"{dst.stem}_try{n}.png")
        tries.append(path)
        _still_at(job_dir, ingest, t + shift, path, duration_s)
        image = cv2.imread(str(path))
        if image is None:
            continue
        clarity = roi_sharpness(image) * (1.0 - hand_fraction(image))
        if best is None or clarity > best[0]:
            best = (clarity, path)
    if best is None:
        return _still_at(job_dir, ingest, t, dst, duration_s)
    best[1].replace(dst)
    for path in tries:
        path.unlink(missing_ok=True)
    return dst


def _keyframe_still(
    job_dir: Path,
    ingest: IngestInfo | None,
    frames: Frames | None,
    step: Step,
    duration_s: float,
) -> Path:
    media = {item.index: item for item in frames.steps} if frames else {}
    item = media.get(step.index)
    if item is not None and item.still:
        candidate = job_dir / item.still
        if candidate.is_file():
            return candidate
    dst = job_dir / "stills" / f"{step.index:02d}.png"
    middle = (step.start_s + step.end_s) / 2
    return _still_at(job_dir, ingest, middle, dst, duration_s)


def _make_overlay(
    job_dir: Path, step: Step, still_path: Path, sp: StepPerception, with_part: bool = True
) -> str:
    """Draw on the still the boxes were found on: the keyframe, or the screw still."""
    image = _read_image(still_path)
    height, width = image.shape[:2]
    longest = max(width, height)
    if longest > 1600:
        factor = 1600 / longest
        image = cv2.resize(
            image,
            (max(1, int(round(width * factor))), max(1, int(round(height * factor)))),
            interpolation=cv2.INTER_AREA,
        )
        height, width = image.shape[:2]
    result = image
    if sp.part is not None and with_part:
        box = sp.part.box
        detection = Detection(
            object_id="part",
            box=(box.x * width, box.y * height, (box.x + box.w) * width, (box.y + box.h) * height),
            confidence=sp.part.confidence,
            mask=None,
            mask_size=None,
            mask_bounds=None,
        )
        result = draw_part(result, detection, (width, height))
    if sp.removed:
        result = draw_screws(
            result,
            [record.box for record in sp.removed],
            [record.number for record in sp.removed],
        )
    relative = f"steps/{step.index:02d}_overlay.jpg"
    save_jpeg(result, job_dir / relative)
    return relative


def _process_step(
    job_dir: Path,
    settings: Settings,
    client: Any,
    plan: Plan,
    frames: Frames | None,
    ingest: IngestInfo | None,
    step: Step,
    sp: StepPerception,
    next_number: int,
    fastener: str = "screw",
    adding: bool = False,
    object_name: str = "",
) -> int:
    context = f"{object_name or plan.device}. Step: {step.title}. {step.instruction}"
    fastener = step_fastener(step, fastener)
    keyframe_path = _keyframe_still(job_dir, ingest, frames, step, plan.duration_s)
    key_image = _read_image(keyframe_path)
    key_h, key_w = key_image.shape[:2]
    concepts = part_concepts(step)
    for concept in concepts:  # plain words first, then shorter fallbacks
        detections, sent_size = _segment(client, sp, keyframe_path, concept, max_side=1600)
        usable = [item for item in detections if _confidence_ok(item)]
        best = max(usable, key=_confidence_value, default=None)
        part_box = _norm_box(best.box, sent_size) if best is not None else None
        if best is not None and part_box is not None:
            sp.part = PartHighlight(concept=concept, box=part_box, confidence=best.confidence)
            break
    if concepts and sp.part is None:
        sp.part = _pointed_part(client, keyframe_path, concepts[0], context)
    if concepts and sp.part is None:
        sp.notes.append(f"No part found for '{concepts[0]}'.")
    screws_still: Path | None = None
    if _screw_count(step) > 0:
        roi = roi_of(sp.part)
        name = f"{step.index:02d}"
        before_path = _clear_still_at(
            job_dir,
            ingest,
            step.start_s - BEFORE_S,
            job_dir / "stills" / f"{name}_before.png",
            plan.duration_s,
        )
        after_path = _clear_still_at(
            job_dir,
            ingest,
            step.end_s + AFTER_S,
            job_dir / "stills" / f"{name}_after.png",
            plan.duration_s,
        )
        before_image = _read_image(before_path)
        after_image = _read_image(after_path)
        alignment = align_after_to_before(before_image, after_image)
        aligned = alignment is not None
        if not aligned:
            sp.notes.append(_align_failed_note(fastener))
        if adding:
            # assembly: the new fasteners are found and drawn on the after still as filmed;
            # the before still's fasteners are moved onto it to see which ones were there
            base_path, base_image = after_path, after_image
            base = fasteners_on_still(
                client, sp, after_path, roi, image=after_image, fastener=fastener
            )
            before = fasteners_on_still(
                client, sp, before_path, roi, image=before_image, fastener=fastener
            )
            other_side = (
                [
                    (
                        _moved(
                            box, cv2.invertAffineTransform(alignment), before_image, after_image
                        ),
                        c,
                    )
                    for box, c in before
                ]
                if aligned
                else []
            )
            sp.screws_before, sp.screws_after = len(before), len(base)
        else:
            # removal: found on the before still; the after still is turned to line up with it
            base_path, base_image = before_path, before_image
            if aligned:
                before_h, before_w = before_image.shape[:2]
                after_for_screws = cv2.warpAffine(after_image, alignment, (before_w, before_h))
            else:
                after_for_screws = after_image
            base = fasteners_on_still(
                client, sp, before_path, roi, image=before_image, fastener=fastener
            )
            other_side = fasteners_on_still(
                client, sp, after_path, roi, image=after_for_screws, fastener=fastener
            )
            sp.screws_before, sp.screws_after = len(base), len(other_side)
        base = pointed_fasteners(
            client, base_path.with_name(f"{base_path.stem}_crop.png"), roi, fastener, context, base
        )
        base = checked_fasteners(client, base_image, base, settings.spark_model, context, fastener)
        screws_still = base_path
        diagonal = math.hypot(key_w, key_h)
        limit = SAME_SCREW * diagonal
        removed: list[tuple[NormBox, float | None]] = []
        for box, confidence in base:
            centre_x, centre_y = _centre(box)
            on_other = any(
                math.hypot(
                    (centre_x - _centre(other)[0]) * key_w,
                    (centre_y - _centre(other)[1]) * key_h,
                )
                <= limit
                for other, _ in other_side
            )
            if not on_other:
                removed.append((box, confidence))
        if _screw_count(step):  # never more than the analysis counted; most confident first
            removed = sorted(removed, key=lambda item: -(item[1] or 0.0))[: _screw_count(step)]
        records: list[ScrewRecord] = []
        for number, (box, confidence) in enumerate(_reading_order(removed), start=1):
            if not aligned:
                confidence = 0.5 if confidence is None else min(confidence, 0.5)
            records.append(
                ScrewRecord(
                    id=f"S{next_number}",
                    number=number,
                    box=box,
                    confidence=confidence,
                )
            )
            next_number += 1
        sp.removed = records
        if len(records) != _screw_count(step):
            sp.notes.append(
                f"SAM found {len(records)} {plural(fastener)} {'put in' if adding else 'removed'}, "
                f"the analysis counted {_screw_count(step)}."
            )
    if screws_still is not None and sp.removed:
        # screw boxes are on the before still (or the after one, when it could not be aligned)
        sp.overlay = _make_overlay(job_dir, step, screws_still, sp, with_part=False)
    else:
        sp.overlay = _make_overlay(job_dir, step, keyframe_path, sp)
    return next_number


def run(job_dir: Path, settings: Settings, client: Any = None) -> Perception:
    """Run SAM on the planned steps and save ``perception.json``."""
    plan = artifacts.load(job_dir, Plan)
    frames = artifacts.load_optional(job_dir, Frames)
    ingest = artifacts.load_optional(job_dir, IngestInfo)
    if client is None:
        client = make_client(settings, job_dir=job_dir)
    fastener = fastener_concept(job_dir)
    identity = artifacts.load_optional(job_dir, Identity)
    adding = identity is not None and identity.task == "assemble"
    object_name = identity.object_name if identity is not None else ""
    eligible = [step for step in plan.steps if _screw_count(step) > 0 or part_concepts(step)]
    prioritised = sorted(eligible, key=lambda step: (-_screw_count(step), step.index))
    selected_indexes = {step.index for step in prioritised[:MAX_STEPS]}
    selected = [step for step in plan.steps if step.index in selected_indexes]
    results: list[StepPerception] = []
    next_number = 1
    for step in selected:
        sp = StepPerception(index=step.index)
        try:
            next_number = _process_step(
                job_dir,
                settings,
                client,
                plan,
                frames,
                ingest,
                step,
                sp,
                next_number,
                fastener,
                adding,
                object_name,
            )
        except BudgetExceeded:
            sp.notes.append(_BUDGET_NOTE)
            results.append(sp)
            break
        except Exception as exc:  # one bad step must not lose the others
            message = str(exc) or type(exc).__name__
            sp.notes.append(f"Perception failed for this step: {message}")
            results.append(sp)
            continue
        results.append(sp)
    perception = Perception(
        steps=results,
        sam_calls=sum(item.sam_calls for item in results),
    )
    artifacts.save(job_dir, perception)
    return perception
