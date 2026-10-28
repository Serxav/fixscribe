"""Perception stage: the part to touch and the fasteners of each step.

For each planned step SAM 3.1 looks for the part on the keyframe still. When the step puts in
or takes out fasteners, ``app.pipeline.fasteners`` finds them on the step clip: SAM proposes,
Spark chooses by number, SAM video follows them and only the ones that steadily appear (when
building) or disappear (when taking apart) join the fastener ledger. They are drawn on the very
frame they were chosen on. A fastener the video does not clearly show is never invented: the
step keeps the analysis count and a note says how many were seen.

Writes ``perception.json``, ``steps/NN_overlay.jpg`` and ``steps/NN_fasteners.json`` (the
tracks the motion stage draws its rings from).
"""

import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import artifacts
from app.config import Settings
from app.meta_client import BudgetExceeded, Detection, make_client
from app.pipeline.analyze import guide_direction
from app.pipeline.fasteners import (
    clean_phrase,
    fastener_concept,
    find_in_step,
    save_found,
    step_fastener,
    step_fasteners,
)
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
from app.text import plural

MAX_STEPS = 12
ROI_GROW = 1.6
MIN_ROI = 0.5  # never search fasteners in less than half the frame: a tiny part is no area
MIN_CONFIDENCE = 0.3
MAX_CONCEPT_TRIES = 3  # SAM calls spent looking for the part of one step

_BUDGET_NOTE = "SAM budget reached."


class Counted:
    """The client, counting the SAM calls made through it."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.sam_calls = 0

    def segment(self, *args: Any, **kwargs: Any) -> Any:
        self.sam_calls += 1
        return self._client.segment(*args, **kwargs)

    def segment_video(self, *args: Any, **kwargs: Any) -> Any:
        self.sam_calls += 1
        return self._client.segment_video(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def part_concepts(step: Step) -> list[str]:
    """The words to ask SAM for the part, best first, without repeats.

    Spark's `sam_concept` (a plain noun chosen to be visible) comes first; then the part names;
    then their last word alone, because SAM finds "leg" when it cannot find "leg frame c".
    """
    names = [step.sam_concept, step.target_part, *(step.removes or [])]
    found: list[str] = []
    for name in names:
        phrase = clean_phrase(name)
        if phrase is None:
            continue
        for candidate in (phrase, phrase.split()[-1]):
            if candidate not in found and (len(candidate) > 2 and not candidate.isdigit()):
                found.append(candidate)
    return found[:MAX_CONCEPT_TRIES]


def part_concept(target_part: str | None, removes: list[str]) -> str | None:
    """One short noun phrase for SAM, from the target part or what it removes."""
    concept = clean_phrase(target_part)
    if concept is not None:
        return concept
    for item in removes or []:
        concept = clean_phrase(item)
        if concept is not None:
            return concept
    return None


def _screw_count(step: Step) -> int:
    return step.screws.count if step.screws else 0


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
    if dst.is_file():
        return dst
    if ingest is None or ingest.source is None:
        raise ValueError("missing ingest.json source for still extraction")
    middle = min(max((step.start_s + step.end_s) / 2, 0.0), duration_s)
    extract_still(find_original(job_dir), ingest.source, middle, dst)
    return dst


def _make_overlay(job_dir: Path, step: Step, image: np.ndarray, sp: StepPerception) -> str:
    """Draw the part (on the keyframe) or the fasteners (on the frame they were chosen on)."""
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
    if sp.removed:
        result = draw_screws(
            image, [record.box for record in sp.removed], [record.number for record in sp.removed]
        )
    elif sp.part is not None:
        box = sp.part.box
        detection = Detection(
            object_id="part",
            box=(box.x * width, box.y * height, (box.x + box.w) * width, (box.y + box.h) * height),
            confidence=sp.part.confidence,
            mask=None,
            mask_size=None,
            mask_bounds=None,
        )
        result = draw_part(image, detection, (width, height))
    else:
        result = image
    relative = f"steps/{step.index:02d}_overlay.jpg"
    save_jpeg(result, job_dir / relative)
    return relative


def _find_part(client: Any, keyframe: Path, step: Step, sp: StepPerception) -> None:
    concepts = part_concepts(step)
    for concept in concepts:  # plain words first, then shorter fallbacks
        detections, sent_size = client.segment(keyframe, concept, max_side=1600)
        usable = [d for d in detections if _confidence_value(d) >= MIN_CONFIDENCE]
        best = max(usable, key=_confidence_value, default=None)
        part_box = _norm_box(best.box, sent_size) if best is not None else None
        if best is not None and part_box is not None:
            sp.part = PartHighlight(concept=concept, box=part_box, confidence=best.confidence)
            return
    if concepts:
        sp.notes.append(f"No part found for '{concepts[0]}'.")


def _process_step(
    job_dir: Path,
    settings: Settings,
    client: Counted,
    plan: Plan,
    frames: Frames | None,
    ingest: IngestInfo | None,
    step: Step,
    sp: StepPerception,
    next_number: int,
    fastener: str,
    adding: bool,
    object_name: str,
) -> int:
    keyframe = _keyframe_still(job_dir, ingest, frames, step, plan.duration_s)
    _find_part(client, keyframe, step, sp)
    image = _read_image(keyframe)
    count = _screw_count(step)
    if count:
        kind = step_fastener(step, fastener)
        context = f"{object_name or plan.device}. Step: {step.title}. {step.instruction}"
        work = job_dir / "steps" / f"{step.index:02d}_work"
        try:
            result = find_in_step(
                client,
                settings.spark_model,
                job_dir / "video.mp4",
                step,
                step_fasteners(step, fastener),
                context,
                adding,
                work,
                plan.duration_s,
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if result is not None:
            found, image = result
            save_found(job_dir, step.index, found)
            seed = found.frames.get(found.seed, {})
            first, last = min(found.frames, default=0), max(found.frames, default=0)
            sp.screws_before = len(found.frames.get(first, {}))
            sp.screws_after = len(found.frames.get(last, {}))
            for number, oid in enumerate(found.kept, start=1):
                box = _norm_box(seed[oid], found.size)
                if box is None:
                    continue
                sp.removed.append(
                    ScrewRecord(
                        id=f"S{next_number}",
                        number=number,
                        box=box,
                        confidence=found.confidence.get(oid),
                    )
                )
                next_number += 1
        seen = len(sp.removed)
        if seen < count:
            verb = "put in" if adding else "taken out"
            sp.notes.append(
                f"{seen} of {count} {plural(kind.split()[-1])} {verb} are clearly visible in "
                "the video; the count comes from the analysis."
            )
    sp.overlay = _make_overlay(job_dir, step, image, sp)
    sp.sam_calls = client.sam_calls
    return next_number


def run(job_dir: Path, settings: Settings, client: Any = None) -> Perception:
    """Find the part and the fasteners of the planned steps and save ``perception.json``."""
    plan = artifacts.load(job_dir, Plan)
    frames = artifacts.load_optional(job_dir, Frames)
    ingest = artifacts.load_optional(job_dir, IngestInfo)
    if client is None:
        client = make_client(settings, job_dir=job_dir)
    fastener = fastener_concept(job_dir)
    identity = artifacts.load_optional(job_dir, Identity)
    adding = guide_direction(identity.task if identity else None) == "assemble"
    object_name = identity.object_name if identity is not None else ""
    eligible = [step for step in plan.steps if _screw_count(step) > 0 or part_concepts(step)]
    prioritised = sorted(eligible, key=lambda step: (-_screw_count(step), step.index))
    selected_indexes = {step.index for step in prioritised[:MAX_STEPS]}
    selected = [step for step in plan.steps if step.index in selected_indexes]
    results: list[StepPerception] = []
    next_number = 1
    for step in selected:
        sp = StepPerception(index=step.index)
        counted = Counted(client)
        try:
            next_number = _process_step(
                job_dir,
                settings,
                counted,
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
            sp.sam_calls = counted.sam_calls
            results.append(sp)
            break
        except Exception as exc:  # one bad step must not lose the others
            message = str(exc) or type(exc).__name__
            sp.notes.append(f"Perception failed for this step: {message}")
            sp.sam_calls = counted.sam_calls
            results.append(sp)
            continue
        results.append(sp)
    perception = Perception(
        steps=results,
        sam_calls=sum(item.sam_calls for item in results),
    )
    artifacts.save(job_dir, perception)
    return perception
