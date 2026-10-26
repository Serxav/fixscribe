"""Turn the raw analysis from Muse Spark into a valid Guide and save guide.json.

Spark can return times past the end of the video, overlapping steps or steps in the wrong
order. This stage fixes what it can, drops what it cannot, and says so in `guide.checks`.
"""

import json
from pathlib import Path
from typing import Any

from app.jobs import write_json_atomic
from app.pipeline.assembly import build_reassembly
from app.schemas import Analysis, DraftStep, Guide, ScrewMap, Step

MIN_STEP_S = 0.5
LOW_CONFIDENCE = 0.5


class GuideError(Exception):
    pass


def clean_times(drafts: list[DraftStep], duration_s: float) -> tuple[list[DraftStep], list[str]]:
    """Clamp to the video, sort, remove overlaps and drop steps that become too short."""
    notes = []
    clamped = []
    for draft in drafts:
        start = min(max(draft.start_s, 0.0), duration_s)
        end = min(max(draft.end_s, 0.0), duration_s)
        clamped.append(draft.model_copy(update={"start_s": start, "end_s": end}))

    kept: list[DraftStep] = []
    for draft in sorted(clamped, key=lambda d: d.start_s):
        start = draft.start_s
        if kept and start < kept[-1].end_s:
            start = kept[-1].end_s  # overlap: the new step starts where the last one ends
        if draft.end_s - start < MIN_STEP_S:
            notes.append(f"Dropped step '{draft.title}': no usable time range in the video.")
            continue
        kept.append(draft.model_copy(update={"start_s": round(start, 2)}))
    return kept, notes


def to_step(index: int, draft: DraftStep) -> Step:
    return Step(
        index=index,
        title=draft.title,
        instruction=draft.instruction or draft.title,
        start_s=draft.start_s,
        end_s=round(draft.end_s, 2),
        target_part=draft.target_part,
        action=draft.action,
        removes=draft.removes,
        screws=ScrewMap(count=draft.screw_count) if draft.screw_count else None,
        warnings=draft.warnings,
        evidence=[item for item in draft.evidence if item.t_s <= draft.end_s + 1.0],
        confidence=draft.confidence,
        review="needs_review" if draft.confidence < LOW_CONFIDENCE else "auto",
    )


def build_guide(analysis: Analysis, duration_s: float, mode: str) -> Guide:
    drafts, checks = clean_times(analysis.steps, duration_s)
    steps = [to_step(i, draft) for i, draft in enumerate(drafts, start=1)]
    reassembly = build_reassembly(steps)
    checks += reassembly.warnings
    low = [step.index for step in steps if step.review == "needs_review"]
    if low:
        checks.append(f"Low confidence, please review steps: {', '.join(map(str, low))}.")
    return Guide(
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
        reassembly=reassembly.steps,
        checks=checks,
    )


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise GuideError(f"cannot read {path.name}") from exc


def run(job_dir: Path, settings: Any) -> Guide:
    analysis = Analysis.model_validate(read_json(job_dir / "analysis.json"))
    if not analysis.steps:
        raise GuideError("no repair steps were found in the video")
    duration_s = float(read_json(job_dir / "ingest.json")["duration_s"])
    transcript = job_dir / "transcript.json"
    mode = read_json(transcript).get("mode", "silent") if transcript.exists() else "silent"
    guide = build_guide(analysis, duration_s, mode)
    write_json_atomic(job_dir / "guide.json", guide.model_dump(mode="json"))
    return guide
