"""Assemble guide.json: the plan, the media of each step and the reassembly guide.

This is the only stage that writes guide.json. It never invents data: every field comes from an
earlier artifact, and what is not verified is said so in `guide.checks`.
"""

from pathlib import Path
from typing import Any

from app import artifacts
from app.domains import profile_for
from app.pipeline.analyze import guide_direction
from app.pipeline.assembly import build_reassembly
from app.pipeline.fasteners import step_fastener
from app.schemas import (
    Box,
    Frames,
    Guide,
    Identity,
    IngestInfo,
    Motion,
    Narration,
    Perception,
    Plan,
    Proof,
    Safety,
    ScrewMap,
    Step,
    StepPerception,
)
from app.text import plural

VERSION = "3"


def unverified_note(kind: str) -> str:
    """Honest note when the fastener count is not verified on the images yet."""
    return (
        f"The {plural(kind)} count comes from the video analysis only;"
        " it has not been verified on the images yet."
    )


UNVERIFIED_SCREWS = unverified_note("screw")
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


def with_motion(steps: list[Step], motion: Motion | None) -> list[Step]:
    """Attach each step's SAM motion clip and part cut-out (from motion.json)."""
    found = {item.index: item for item in motion.steps} if motion else {}
    return [
        step.model_copy(update={"motion": found[step.index]}) if step.index in found else step
        for step in steps
    ]


def with_kind(steps: list[Step], kind: str) -> list[Step]:
    """Label every fastener map with what the step handles ("pin", "bolt", "dowel"...),
    else the domain fastener kind (screws, bolts, ...)."""
    return [
        step.model_copy(
            update={
                "screws": step.screws.model_copy(
                    update={"kind": step_fastener(step, kind).split()[-1]}
                )
            }
        )
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
    motion: Motion | None = None,
    narration: Narration | None = None,
) -> Guide:
    steps, perception_notes = with_perception(with_media(plan.steps, frames), perception)
    steps = with_motion(steps, motion)
    kind = profile_for(identity.category).fastener_kind if identity else "screw"
    steps = with_kind(steps, kind)
    direction = guide_direction(identity.task if identity else None)
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
        assembled = build_reassembly(steps, direction)
        reassembly = assembled.steps
        checks += assembled.warnings
        if any(step.screws and step.screws.count for step in steps) and not screws_verified(steps):
            checks.append(unverified_note(kind))
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
        narration=narration,
        direction=direction,
    )


SHARP_SIDE = 1080  # below this short side a few-pixel screw is hard to see


def filming_note(ingest: IngestInfo | None, steps: list[Step]) -> str | None:
    """A plain warning when the video is too small for the fasteners the guide counts."""
    if ingest is None or ingest.source is None:
        return None
    if not any(step.screws and step.screws.count for step in steps):
        return None
    short = min(ingest.source.width, ingest.source.height)
    if short >= SHARP_SIDE:
        return None
    return (
        f"The video is {short}p: small fasteners may not be found. For the best result, film "
        f"in {SHARP_SIDE}p or more, close to the part, and show each fastener for a second."
    )


def run(job_dir: Path, settings: Any) -> Guide:
    guide = build_guide(
        artifacts.load(job_dir, Plan),
        artifacts.load_optional(job_dir, Frames),
        artifacts.load_optional(job_dir, Perception),
        artifacts.load_optional(job_dir, Identity),
        artifacts.load_optional(job_dir, Safety),
        artifacts.load_optional(job_dir, Proof),
        artifacts.load_optional(job_dir, Motion),
        artifacts.load_optional(job_dir, Narration),
    )
    note = filming_note(artifacts.load_optional(job_dir, IngestInfo), guide.steps)
    if note:
        guide.checks.append(note)
    artifacts.save(job_dir, guide)
    return guide
