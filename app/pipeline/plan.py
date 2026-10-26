"""Decide the final steps and their times (plan.json).

Inputs: Spark's draft steps (analysis.json) and, when it exists, the fusion of those steps with the
voice and visual evidence (fusion.json). Spark can return times past the end of the video,
overlapping steps or steps in the wrong order: this stage fixes what it can, drops what it cannot,
and writes every change into `plan.checks`, so nothing moves silently.
"""

from pathlib import Path
from typing import Any

from app import artifacts
from app.schemas import (
    Analysis,
    DraftStep,
    Fusion,
    IngestInfo,
    Plan,
    Refine,
    ScrewMap,
    Step,
    Transcript,
)

VERSION = "2"
MIN_STEP_S = 0.5
LOW_CONFIDENCE = 0.5
LOGGED_SHIFT_S = 0.5  # smaller moves are rounding, not worth a note


class PlanError(Exception):
    pass


def apply_fusion(drafts: list[DraftStep], fusion: Fusion | None) -> list[DraftStep]:
    """Use the fused boundaries and confidence. Fusion numbers steps 1.. in Spark's time order."""
    ordered = sorted(drafts, key=lambda d: d.start_s)
    if fusion is None:
        return ordered
    fused = {item.index: item for item in fusion.steps}
    return [
        draft.model_copy(
            update={"start_s": f.start_s, "end_s": f.end_s, "confidence": f.confidence}
        )
        if (f := fused.get(i)) is not None
        else draft
        for i, draft in enumerate(ordered, start=1)
    ]


def apply_refine(drafts: list[DraftStep], refine: Refine | None) -> list[DraftStep]:
    """Use the second Spark pass for the steps it looked at again (numbered like fusion)."""
    if refine is None:
        return drafts
    refined = {item.index: item for item in refine.steps}
    out = []
    for i, draft in enumerate(drafts, start=1):
        r = refined.get(i)
        # Pass 2 only replaces a step when it is at least as sure as what we already have; an
        # answer that failed its sanity checks comes back with low confidence and is ignored.
        if r is None or r.end_s <= r.start_s or r.confidence < draft.confidence:
            out.append(draft)
            continue
        out.append(
            draft.model_copy(
                update={
                    "start_s": r.start_s,
                    "end_s": r.end_s,
                    "instruction": r.instruction or draft.instruction,
                    "action": r.action,
                    "removes": r.removes or draft.removes,
                    "screw_count": r.screw_count,
                    "warnings": r.warnings,
                    "confidence": r.confidence,
                }
            )
        )
    return out


def clean_times(drafts: list[DraftStep], duration_s: float) -> tuple[list[DraftStep], list[str]]:
    """Clamp to the video, sort, remove overlaps, drop steps that become too short. Log changes."""
    notes = []
    kept: list[DraftStep] = []
    for draft in sorted(drafts, key=lambda d: d.start_s):
        start = min(max(draft.start_s, 0.0), duration_s)
        end = min(max(draft.end_s, 0.0), duration_s)
        if abs(end - draft.end_s) > LOGGED_SHIFT_S or abs(start - draft.start_s) > LOGGED_SHIFT_S:
            notes.append(
                f"Step '{draft.title}': times {draft.start_s:.1f}–{draft.end_s:.1f} s were outside "
                f"the video and became {start:.1f}–{end:.1f} s."
            )
        if kept and start < kept[-1].end_s:
            if kept[-1].end_s - start > LOGGED_SHIFT_S:
                notes.append(
                    f"Step '{draft.title}' overlapped the previous step: its start moved from "
                    f"{start:.1f} s to {kept[-1].end_s:.1f} s."
                )
            start = kept[-1].end_s
        if end - start < MIN_STEP_S:
            notes.append(f"Dropped step '{draft.title}': no usable time range in the video.")
            continue
        kept.append(draft.model_copy(update={"start_s": round(start, 2), "end_s": round(end, 2)}))
    return kept, notes


def to_step(index: int, draft: DraftStep) -> Step:
    return Step(
        index=index,
        title=draft.title,
        instruction=draft.instruction or draft.title,
        start_s=draft.start_s,
        end_s=draft.end_s,
        target_part=draft.target_part or None,
        action=draft.action,
        removes=draft.removes,
        screws=ScrewMap(count=draft.screw_count) if draft.screw_count else None,
        warnings=draft.warnings,
        # Only evidence that belongs to this step (1 s of slack for rounding).
        evidence=[
            item for item in draft.evidence if draft.start_s - 1.0 <= item.t_s <= draft.end_s + 1.0
        ],
        confidence=draft.confidence,
        review="needs_review" if draft.confidence < LOW_CONFIDENCE else "auto",
    )


def build_plan(
    analysis: Analysis,
    fusion: Fusion | None,
    duration_s: float,
    mode: str,
    refine: Refine | None = None,
) -> Plan:
    fused = apply_refine(apply_fusion(analysis.steps, fusion), refine)
    drafts, checks = clean_times(fused, duration_s)
    steps = [to_step(i, draft) for i, draft in enumerate(drafts, start=1)]
    low = [step.index for step in steps if step.review == "needs_review"]
    if low:
        checks.append(f"Low confidence, please review steps: {', '.join(map(str, low))}.")
    return Plan(
        title=analysis.title,
        device=analysis.device,
        summary=analysis.summary,
        difficulty=analysis.difficulty,
        estimated_minutes=analysis.estimated_minutes,
        mode=mode,
        duration_s=duration_s,
        tools=analysis.tools,
        parts=analysis.parts,
        warnings=analysis.warnings,
        steps=steps,
        checks=checks,
    )


def run(job_dir: Path, settings: Any) -> Plan:
    analysis = artifacts.load(job_dir, Analysis)
    if not analysis.steps:
        raise PlanError("no repair steps were found in the video")
    ingest = artifacts.load(job_dir, IngestInfo)
    transcript = artifacts.load_optional(job_dir, Transcript)
    fusion = artifacts.load_optional(job_dir, Fusion)
    refine = artifacts.load_optional(job_dir, Refine)
    mode = transcript.mode if transcript else "silent"
    plan = build_plan(analysis, fusion, ingest.duration_s, mode, refine)
    if not plan.steps:
        raise PlanError("no repair step had a usable time range in the video")
    artifacts.save(job_dir, plan)
    return plan
