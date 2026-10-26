"""Assemble guide.json: the plan, the media of each step and the reassembly guide.

This is the only stage that writes guide.json. It never invents data: every field comes from an
earlier artifact, and what is not verified is said so in `guide.checks`.
"""

from pathlib import Path
from typing import Any

from app import artifacts
from app.pipeline.assembly import build_reassembly
from app.schemas import Frames, Guide, Plan, Step

VERSION = "2"
UNVERIFIED_SCREWS = (
    "Screw counts come from the video analysis only; they have not been verified on the images yet."
)


def with_media(steps: list[Step], frames: Frames | None) -> list[Step]:
    media = {item.index: item for item in frames.steps} if frames else {}
    return [
        step.model_copy(update={"keyframe_s": m.keyframe_s, "image": m.image, "clip": m.clip})
        if (m := media.get(step.index)) is not None
        else step
        for step in steps
    ]


def screws_verified(steps: list[Step]) -> bool:
    """True only when every step with screws has screw positions found on its images."""
    with_screws = [step for step in steps if step.screws and step.screws.count]
    return bool(with_screws) and all(step.screws.boxes for step in with_screws)


def build_guide(plan: Plan, frames: Frames | None) -> Guide:
    steps = with_media(plan.steps, frames)
    reassembly = build_reassembly(steps)
    checks = list(plan.checks) + reassembly.warnings
    if any(step.screws and step.screws.count for step in steps) and not screws_verified(steps):
        checks.append(UNVERIFIED_SCREWS)
    return Guide(
        title=plan.title,
        device=plan.device,
        summary=plan.summary,
        difficulty=plan.difficulty,
        estimated_minutes=plan.estimated_minutes,
        mode=plan.mode,
        duration_s=plan.duration_s,
        tools=plan.tools,
        parts=plan.parts,
        warnings=plan.warnings,
        steps=steps,
        reassembly=reassembly.steps,
        checks=checks,
    )


def run(job_dir: Path, settings: Any) -> Guide:
    guide = build_guide(artifacts.load(job_dir, Plan), artifacts.load_optional(job_dir, Frames))
    artifacts.save(job_dir, guide)
    return guide
