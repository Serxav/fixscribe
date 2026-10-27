"""Step check ("ghost camera"): is this step done on the user's own object?

The user does one step of a guide on their own object and takes a photo.
We align the photo to the guide still just after the step, count the
fasteners SAM 3.1 still sees with the same helpers the perception stage
uses, and answer "done" / "not_yet" / "unclear". Each answer is saved as
``checks/step_NN_<k>.json``; this stage writes no other result file.
"""

import io
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from app import artifacts
from app.artifacts import ArtifactError
from app.config import Settings
from app.meta_client import BudgetExceeded, make_client
from app.pipeline.ingest import IngestError, find_original
from app.pipeline.media import extract_still
from app.pipeline.perception import (
    AFTER_S,
    align_after_to_before,
    fastener_concept,
    fasteners_on_still,
    roi_of,
)
from app.schemas import Guide, IngestInfo, Perception, Step, StepCheck, StepPerception

MAX_PHOTO_BYTES = 15 * 1024**2
MAX_CHECKS_PER_JOB = 20


class StepCheckError(Exception):
    """A user-facing reason the photo could not be checked."""


class CheckLimitReached(StepCheckError):
    """This job already answered MAX_CHECKS_PER_JOB photos (protects the Meta budget)."""


def load_photo(data: bytes) -> np.ndarray:
    """Phone photo bytes to a BGR array, upright whatever the EXIF rotation tag says."""
    if len(data) > MAX_PHOTO_BYTES:
        raise StepCheckError(f"photo is too big ({len(data)} bytes, max {MAX_PHOTO_BYTES} bytes)")
    if not data:
        raise StepCheckError("photo is empty")
    try:
        with Image.open(io.BytesIO(data)) as image:
            pixels = np.asarray(ImageOps.exif_transpose(image).convert("RGB"))
    except StepCheckError:
        raise
    except Exception as exc:
        raise StepCheckError(f"could not read the photo: {exc}") from exc
    return cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)


def reference_still(job_dir: Path, guide: Guide, step: Step) -> Path:
    """The guide still just after the step, extracted once from the original video."""
    dst = job_dir / "checks" / f"ref_{step.index:02d}.png"
    if dst.is_file():
        return dst
    ingest = artifacts.load_optional(job_dir, IngestInfo)
    if ingest is None or ingest.source is None:
        raise StepCheckError("no video source to compare the photo with")
    try:
        original = find_original(job_dir)
    except IngestError as exc:
        raise StepCheckError(f"no video source to compare the photo with: {exc}") from exc
    duration = guide.duration_s or ingest.duration_s
    t = min(max(step.end_s + AFTER_S, 0.0), duration)
    try:
        extract_still(original, ingest.source, t, dst)
    except Exception as exc:
        raise StepCheckError(f"could not extract the guide still: {exc}") from exc
    return dst


def _save_result(checks_dir: Path, index: int, number: int, result: StepCheck) -> None:
    path = checks_dir / f"step_{index:02d}_{number}.json"
    artifacts.write_json_atomic(path, result.model_dump(mode="json"))


def check_step(
    job_dir: Path,
    settings: Settings,
    step_index: int,
    photo: bytes,
    client: Any = None,
) -> StepCheck:
    """Check the user's photo of one step and save the answer. Raises StepCheckError."""
    try:
        guide = artifacts.load(job_dir, Guide)
    except ArtifactError as exc:
        raise StepCheckError(f"no guide for this job: {exc}") from exc
    perception = artifacts.load_optional(job_dir, Perception)
    step = next((item for item in guide.steps if item.index == step_index), None)
    if step is None:
        raise StepCheckError(f"unknown step: {step_index}")
    checks_dir = job_dir / "checks"
    existing = sorted(checks_dir.glob("step_*.json")) if checks_dir.is_dir() else []
    if len(existing) >= MAX_CHECKS_PER_JOB:
        raise CheckLimitReached(
            f"check limit reached for this job ({MAX_CHECKS_PER_JOB} checks max)"
        )
    number = len(existing) + 1
    while (checks_dir / f"step_{step.index:02d}_{number}.json").exists():
        number += 1
    kind = step.screws.kind if step.screws else fastener_concept(job_dir)
    if not step.screws or step.screws.count == 0:
        result = StepCheck(
            step=step.index,
            verdict="unclear",
            message=(
                "This step has no fasteners to check. Compare your photo with the guide image."
            ),
            fastener_kind=kind,
        )
        _save_result(checks_dir, step.index, number, result)
        return result
    photo_img = load_photo(photo)
    ref_path = reference_still(job_dir, guide, step)
    ref_img = cv2.imread(str(ref_path))
    if ref_img is None:
        raise StepCheckError(f"could not read the guide still: {ref_path.name}")
    matrix = align_after_to_before(ref_img, photo_img)
    if matrix is not None:
        ref_h, ref_w = ref_img.shape[:2]
        probe_img = cv2.warpAffine(photo_img, matrix, (ref_w, ref_h))
        aligned = True
    else:
        probe_img = photo_img
        aligned = False
    step_perception: StepPerception | None = None
    if perception is not None:
        step_perception = next(
            (item for item in perception.steps if item.index == step.index), None
        )
    region = roi_of(step_perception.part if step_perception else None)
    if client is None:
        client = make_client(settings, job_dir=job_dir)
    photo_path = checks_dir / f"step_{step.index:02d}_photo_{number}.png"
    photo_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(photo_path), photo_img):
        raise StepCheckError("could not save the photo")
    calls = StepPerception(index=step.index)
    try:
        found = fasteners_on_still(
            client, calls, photo_path, region, image=probe_img, fastener=kind
        )
    except BudgetExceeded as exc:
        raise StepCheckError("budget reached") from exc
    expected = step_perception.screws_after if step_perception else None
    count = len(found)
    plural = f"{kind}s"
    result = StepCheck(
        step=step.index,
        verdict="unclear",
        message="",
        fastener_kind=kind,
        expected_left=expected,
        found=count,
        boxes=[box for box, _ in found],
        aligned=aligned,
        sam_calls=calls.sam_calls,
    )
    if expected is None or not aligned:
        if aligned:
            result.message = (
                f"SAM found {count} {plural}, but the guide has no measurement to compare with."
            )
        else:
            result.message = (
                f"SAM found {count} {plural}; the photo could not be matched to the guide."
            )
    elif count <= expected:
        result.verdict = "done"
        result.message = f"No {plural} left where the guide removes them."
    else:
        result.verdict = "not_yet"
        result.message = f"{count - expected} {plural} are still in place."
    _save_result(checks_dir, step.index, number, result)
    return result
