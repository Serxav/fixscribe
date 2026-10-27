"""Perception stage: SAM part highlight and before/after screw ledger.

For each planned step SAM 3.1 looks for the part on the keyframe still and,
when the step removes screws, for screws on stills just before and just
after the step. Screws are searched on native-resolution crops around the
part, upscaled so a few-pixel screw becomes visible. A screw present before
and missing after was removed in that step and joins the screw ledger.
Everything is saved in ``perception.json``; this stage writes no other
artifact.
"""

import math
import os
import statistics
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import artifacts
from app.config import Settings
from app.domains import profile_for
from app.meta_client import BudgetExceeded, Detection, make_client
from app.pipeline.ingest import find_original
from app.pipeline.media import extract_still
from app.pipeline.overlay import draw_part, draw_screws, save_jpeg
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

MAX_STEPS = 12
BEFORE_S = 0.5
AFTER_S = 0.5
ROI_GROW = 1.6
MIN_CROP_SIDE = 900
MIN_CONFIDENCE = 0.3
NMS_IOU = 0.5
SAME_SCREW = 0.04

_ARTICLES = {"a", "an", "the"}
_BUDGET_NOTE = "SAM budget reached."


def fastener_concept(job_dir: Path) -> str:
    """The SAM fastener word for this job: the profile kind, or "screw"."""
    identity = artifacts.load_optional(job_dir, Identity)
    if identity is None:
        return "screw"
    return profile_for(identity.category).fastener_kind


def _plural(concept: str) -> str:
    return concept + "s"


def _clean_phrase(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = "".join(
        ch if ch.isalnum() or ch.isspace() or ch == "-" else " " for ch in text.lower()
    )
    words = [word for word in cleaned.split() if word not in _ARTICLES]
    if not words:
        return None
    return " ".join(words[-2:])


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
    grown_w = min(1.0, box.w * ROI_GROW)
    grown_h = min(1.0, box.h * ROI_GROW)
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
    return f"Camera moved too much to verify the {_plural(fastener)}."


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


def _write_png_atomic(image: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.tmp.png")
    try:
        if not cv2.imwrite(str(tmp), image):
            raise OSError(f"cannot write image: {path}")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


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
    kept = _nms([item for item in detections if _confidence_ok(item)])
    found: list[tuple[NormBox, float | None]] = []
    for detection in kept:
        box = _map_to_still(detection, sent_size, roi)
        if box is not None:
            found.append((box, detection.confidence))
    return found


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


def _make_overlay(job_dir: Path, step: Step, keyframe_path: Path, sp: StepPerception) -> str:
    image = _read_image(keyframe_path)
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
    if sp.part is not None:
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
) -> int:
    del settings
    keyframe_path = _keyframe_still(job_dir, ingest, frames, step, plan.duration_s)
    key_image = _read_image(keyframe_path)
    key_h, key_w = key_image.shape[:2]
    concept = part_concept(step.target_part, step.removes)
    if concept is not None:
        detections, sent_size = _segment(client, sp, keyframe_path, concept, max_side=1600)
        usable = [item for item in detections if _confidence_ok(item)]
        best = max(usable, key=_confidence_value, default=None)
        part_box = _norm_box(best.box, sent_size) if best is not None else None
        if best is not None and part_box is not None:
            sp.part = PartHighlight(concept=concept, box=part_box, confidence=best.confidence)
        else:
            sp.notes.append(f"No part found for '{concept}'.")
    if _screw_count(step) > 0:
        roi = roi_of(sp.part)
        name = f"{step.index:02d}"
        before_path = _still_at(
            job_dir,
            ingest,
            step.start_s - BEFORE_S,
            job_dir / "stills" / f"{name}_before.png",
            plan.duration_s,
        )
        after_path = _still_at(
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
        if aligned:
            before_h, before_w = before_image.shape[:2]
            after_for_screws = cv2.warpAffine(after_image, alignment, (before_w, before_h))
        else:
            after_for_screws = after_image
            sp.notes.append(_align_failed_note(fastener))
        before = fasteners_on_still(
            client, sp, before_path, roi, image=before_image, fastener=fastener
        )
        sp.screws_before = len(before)
        after = fasteners_on_still(
            client, sp, after_path, roi, image=after_for_screws, fastener=fastener
        )
        sp.screws_after = len(after)
        diagonal = math.hypot(key_w, key_h)
        limit = SAME_SCREW * diagonal
        removed: list[tuple[NormBox, float | None]] = []
        for box, confidence in before:
            centre_x, centre_y = _centre(box)
            still_there = any(
                math.hypot(
                    (centre_x - _centre(other)[0]) * key_w,
                    (centre_y - _centre(other)[1]) * key_h,
                )
                <= limit
                for other, _ in after
            )
            if not still_there:
                removed.append((box, confidence))
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
                f"SAM found {len(records)} {_plural(fastener)} removed, "
                f"the analysis counted {_screw_count(step)}."
            )
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
    eligible = [
        step
        for step in plan.steps
        if _screw_count(step) > 0 or part_concept(step.target_part, step.removes) is not None
    ]
    prioritised = sorted(eligible, key=lambda step: (-_screw_count(step), step.index))
    selected_indexes = {step.index for step in prioritised[:MAX_STEPS]}
    selected = [step for step in plan.steps if step.index in selected_indexes]
    results: list[StepPerception] = []
    next_number = 1
    for step in selected:
        sp = StepPerception(index=step.index)
        try:
            next_number = _process_step(
                job_dir, settings, client, plan, frames, ingest, step, sp, next_number, fastener
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
