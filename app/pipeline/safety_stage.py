"""Safety stage: deterministic rules over every word we have, before any model.

Reads identity.json (optional), plan.json and transcript.json (optional), merges the domain's
default hazards into the identity, and writes safety.json with `evaluate`. No Meta call here:
a model may only make this decision stricter later, via `stricter()`."""

from pathlib import Path
from typing import Any

from app import artifacts
from app.domains import profile_for
from app.safety import evaluate
from app.schemas import Identity, Plan, Safety, Transcript

VERSION = "1"


def job_texts(plan: Plan, transcript: Transcript | None) -> list[str]:
    """Every word we have about the job: the plan and, when it exists, the speech."""
    texts = [plan.title, plan.device, plan.summary, *plan.warnings]
    for step in plan.steps:
        texts += [step.title, step.instruction, step.target_part or "", *step.removes]
        texts += step.warnings
    if transcript is not None:
        if transcript.turns:
            texts += [turn.text for turn in transcript.turns]
        elif transcript.transcript:
            texts.append(transcript.transcript)
    return texts


def run(job_dir: Path, settings: Any) -> Safety:
    """Merge the domain hazards into the identity and save the rules-only decision."""
    identity = artifacts.load_optional(job_dir, Identity)
    plan = artifacts.load(job_dir, Plan)
    transcript = artifacts.load_optional(job_dir, Transcript)
    profile = profile_for(identity.category if identity else None)
    if identity is not None:
        hazards = list(identity.hazards)
        hazards += [h for h in profile.default_hazards if h not in hazards]
        identity = identity.model_copy(update={"hazards": hazards})
    safety = evaluate(identity, job_texts(plan, transcript), profile.prechecks)
    artifacts.save(job_dir, safety)
    return safety
