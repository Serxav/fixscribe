"""Assemble guide.json: the plan, the media of each step and the reassembly guide.

This is the only stage that writes guide.json. It never invents data: every field comes from an
earlier artifact, and what is not verified is said so in `guide.checks`.
"""

from pathlib import Path
from typing import Any

from app import artifacts
from app.domains import profile_for
from app.pipeline.assembly import build_reassembly
from app.schemas import (
    Box,
    Frames,
    Guide,
    Identity,
    Perception,
    Plan,
    Proof,
    Safety,
    ScrewMap,
    Step,
    StepPerception,
)

VERSION = "3"
UNVERIFIED_SCREWS = (
    "Screw counts come from the video analysis only; they have not been verified on the images yet."
)
PRO_ONLY_STEP = (
    "A qualified professional must do this step. FixScribe does not give instructions for it."
)
PRO_ONLY_CHECK = "Professional-only job:"


def with_media(steps: list[Step], frames: Frames | None) -> list[Step]:
    media = {item.index: item for item in frames.steps} if frames else {}
    return [
        step.model_copy(update={"keyframe_s": m.keyframe_s, "image": m.image, "clip": m.clip})
        if (m := media.get(step.index)) is not None
        else step
        for step in steps
    ]


def to_box(number: int, x: float, y: float, w: float, h: float) -> Box:
    """A screw-map box, clamped so it stays inside the image."""
    w, h = min(w, 1.0), min(h, 1.0)
    return Box(number=number, x=min(max(x, 0.0), 1.0 - w), y=min(max(y, 0.0), 1.0 - h), w=w, h=h)


def with_perception(
    steps: list[Step], perception: Perception | None
) -> tuple[list[Step], list[str]]:
    """Add SAM's screw positions and overlay to each step, and its notes to the checks."""
    if perception is None:
        return steps, []
    found: dict[int, StepPerception] = {item.index: item for item in perception.steps}
    merged, notes = [], []
    for step in steps:
        seen = found.get(step.index)
        if seen is None:
            merged.append(step)
            continue
        notes += [f"Step {step.index}: {note}" for note in seen.notes]
        update: dict = {}
        if seen.overlay:
            update["overlay"] = seen.overlay
        if seen.removed:
            boxes = [to_box(r.number, r.box.x, r.box.y, r.box.w, r.box.h) for r in seen.removed]
            # The analysis count stays the claim; SAM's boxes are the evidence that checks it.
            count = step.screws.count if step.screws and step.screws.count else len(boxes)
            update["screws"] = ScrewMap(count=count, boxes=boxes)
        merged.append(step.model_copy(update=update) if update else step)
    return merged, notes


def screws_verified(steps: list[Step]) -> bool:
    """True only when every step with screws has screw positions found on its images."""
    with_screws = [step for step in steps if step.screws and step.screws.count]
    return bool(with_screws) and all(step.screws.boxes for step in with_screws)


def with_kind(steps: list[Step], kind: str) -> list[Step]:
    """Label every screw map with the domain fastener kind (screws, bolts, ...)."""
    return [
        step.model_copy(update={"screws": step.screws.model_copy(update={"kind": kind})})
        if step.screws
        else step
        for step in steps
    ]


def with_prechecks(warnings: list[str], prechecks: list[str]) -> list[str]:
    """The safety prechecks first, then the plan warnings, without duplicates."""
    return list(dict.fromkeys([*prechecks, *warnings]))


def blocked_steps(steps: list[Step]) -> list[Step]:
    """The same steps without instructions: a pro must do them, we only point at them."""
    return [step.model_copy(update={"instruction": PRO_ONLY_STEP}) for step in steps]


def build_guide(
    plan: Plan,
    frames: Frames | None,
    perception: Perception | None = None,
    identity: Identity | None = None,
    safety: Safety | None = None,
    proof: Proof | None = None,
) -> Guide:
    steps, perception_notes = with_perception(with_media(plan.steps, frames), perception)
    steps = with_kind(steps, profile_for(identity.category).fastener_kind if identity else "screw")
    level = safety.level if safety else "normal"
    warnings = (
        plan.warnings if level == "normal" else with_prechecks(plan.warnings, safety.prechecks)
    )
    checks = list(plan.checks) + perception_notes
    if level == "professional_only":
        # We show what the job involves, never how to do it.
        steps, reassembly = blocked_steps(steps), []
        checks.append(PRO_ONLY_CHECK + " " + " ".join(safety.reasons))
    else:
        assembled = build_reassembly(steps)
        reassembly = assembled.steps
        checks += assembled.warnings
        if any(step.screws and step.screws.count for step in steps) and not screws_verified(steps):
            checks.append(UNVERIFIED_SCREWS)
    return Guide(
        title=plan.title,
        device=plan.device,
        summary=plan.summary,
        difficulty=plan.difficulty,
        estimated_minutes=plan.estimated_minutes,
        mode=plan.mode,
        language=identity.language if identity else "en",
        duration_s=plan.duration_s,
        tools=plan.tools,
        parts=plan.parts,
        warnings=warnings,
        steps=steps,
        reassembly=reassembly,
        checks=checks,
        identity=identity,
        safety=safety,
        proof=proof,
    )


def run(job_dir: Path, settings: Any) -> Guide:
    guide = build_guide(
        artifacts.load(job_dir, Plan),
        artifacts.load_optional(job_dir, Frames),
        artifacts.load_optional(job_dir, Perception),
        artifacts.load_optional(job_dir, Identity),
        artifacts.load_optional(job_dir, Safety),
        artifacts.load_optional(job_dir, Proof),
    )
    artifacts.save(job_dir, guide)
    return guide
