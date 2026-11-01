"""Prove every claim of the guide with the evidence behind it (proof.json).

Deterministic stage, no Meta call. For every planned step each claim (boundaries,
instruction, fastener count, part) gets a status -- verified, supported or unverified --
and human-readable sources: video seconds, spoken words, SAM measurements.
"""

from pathlib import Path
from typing import Any

from app import artifacts
from app.schemas import (
    Claim,
    Fusion,
    FusionStep,
    Perception,
    Plan,
    Proof,
    Refine,
    RefinedStep,
    Step,
    StepPerception,
    StepProof,
    StepReview,
    Transcript,
)
from app.text import plural

VERSION = "1"
REFINE_CONFIDENCE = 0.7  # a timecode re-check below this is not trusted
PART_CONFIDENCE = 0.5  # SAM below this only supports the part claim
MAX_TURNS = 2  # transcript turns quoted per step
TURN_CUT = 80  # characters kept per quoted turn

# Index rule: fusion and refine number Spark's drafts 1, 2, 3... in time order; the plan keeps
# that number in `step.source_index` (it can differ from `step.index` when the plan drops a
# step). Perception entries carry the plan step index.
REVIEW_CONFIDENCE = 0.7  # a frame by frame review below this proves nothing
MIN_SHARED = 0.5  # at least this much of the reviewed time must fall inside the step
SCORES = {"verified": 1.0, "supported": 0.5, "unverified": 0.0}


def review_times(step: Step, review: StepReview | None) -> tuple[float, float] | None:
    """The seconds a confident review read from the frames, when they are about this same step.

    The frames are stronger evidence than the first draft's cut, so the guide moves to them. A
    review that barely touches the step is talking about something else and moves nothing.
    """
    if review is None or review.confidence < REVIEW_CONFIDENCE or review.end_s <= review.start_s:
        return None
    shared = min(review.end_s, step.end_s) - max(review.start_s, step.start_s)
    if shared < MIN_SHARED * (review.end_s - review.start_s):
        return None
    return review.start_s, review.end_s


def rewritten_by_review(step: Step, review: StepReview | None) -> bool:
    """True when the review said the frames show something else and gave the sentence for it."""
    return bool(
        review
        and not review.matches
        and review.confidence >= REVIEW_CONFIDENCE
        and review.instruction.strip()
    )


def same_part(found: str, wanted: str) -> bool:
    """True when two names share a word: "phone battery" is the "battery", a "plate" is not."""
    return bool(set(found.lower().split()) & set(wanted.lower().split()))


def boundaries_claim(
    step: Step,
    fusion_step: FusionStep | None,
    refined: RefinedStep | None,
    review: StepReview | None = None,
) -> Claim:
    """Where the step starts and ends, from fusion signals and the timecode re-check."""
    names = {"voice": "voice cut at {}", "pause": "pause at {}", "scene": "scene change at {}"}
    sources = []
    signal = False
    if fusion_step is not None:
        for source, t in (
            (fusion_step.start_source, fusion_step.start_s),
            (fusion_step.end_source, fusion_step.end_s),
        ):
            if source != "spark":
                sources.append(names[source].format(f"{t:.1f} s"))
                signal = True
    rechecked = refined is not None and refined.confidence >= REFINE_CONFIDENCE
    if rechecked:
        sources.append(f"timecode re-check: {refined.start_s:.1f}–{refined.end_s:.1f} s")
    agrees = review_times(step, review) is not None
    if agrees:
        sources.append(f"frame by frame review: {review.start_s:.1f}–{review.end_s:.1f} s")
    if agrees or (signal and rechecked):
        status = "verified"
    elif signal or rechecked:
        status = "supported"
    else:
        status = "unverified"
    return Claim(field="boundaries", status=status, sources=sources)


def instruction_claim(
    step: Step, transcript: Transcript | None, review: StepReview | None = None
) -> Claim:
    """What to do, from the step evidence and the spoken turns overlapping it."""
    sources = []
    for item in step.evidence:
        if item.source == "video":
            sources.append(f"video {item.t_s:.1f} s: {item.text}")
        else:
            sources.append(f"voice {item.t_s:.1f} s: '{item.text}'")
    if transcript is not None:
        overlapping = [
            turn
            for turn in transcript.turns
            if turn.start_s <= step.end_s and turn.end_s >= step.start_s
        ]
        for turn in overlapping[:MAX_TURNS]:
            sources.append(f"voice {turn.start_s:.1f} s: '{turn.text[:TURN_CUT]}'")
    video = any(source.startswith("video") for source in sources)
    voice = any(source.startswith("voice") for source in sources)
    confident = review is not None and review.confidence >= REVIEW_CONFIDENCE
    if rewritten_by_review(step, review):
        # the guide now says what the frames show, in the review's own words
        return Claim(
            field="instruction",
            status="verified",
            sources=[f"rewritten from the frame by frame review: {review.instruction}"],
        )
    if confident and not review.matches:
        # the frames say otherwise and gave no sentence: this one is not proven
        return Claim(
            field="instruction",
            status="unverified",
            sources=[*sources, "frame by frame review disagrees"],
        )
    if confident:
        sources.append("frame by frame review: the frames show this")
    if confident or (video and voice):
        status = "verified"
    elif sources:
        status = "supported"
    else:
        status = "unverified"
    return Claim(field="instruction", status=status, sources=sources)


def fastener_claim(
    step: Step, step_perception: StepPerception | None, refined: RefinedStep | None
) -> Claim | None:
    """How many fasteners come out, from SAM's before/after count and the re-check."""
    if not step.screws or step.screws.count <= 0:
        return None
    kind = plural(step.screws.kind)
    sources = []
    ran = step_perception is not None
    records = step_perception.removed if step_perception is not None else []
    pointed = sum(record.pointed for record in records)
    removed = len(records) - pointed
    if ran:
        sources.append(f"SAM: {removed} {kind} removed (before/after stills)")
    if pointed:
        sources.append(f"Muse Spark saw the tool stop at {pointed} spots: too small for SAM to cut")
    agrees = refined is not None and refined.screw_count == step.screws.count
    if refined is not None:
        sources.append(f"timecode re-check counted {refined.screw_count}")
    if ran and removed == step.screws.count:
        status = "verified"
    elif (ran and removed > 0 and removed != step.screws.count) or agrees or pointed:
        status = "supported"
    else:
        status = "unverified"
    return Claim(field="fastener_count", status=status, sources=sources)


def part_claim(step: Step, step_perception: StepPerception | None) -> Claim | None:
    """Which part to touch, from what SAM found on the step stills."""
    if not step.target_part:
        return None
    part = step_perception.part if step_perception is not None else None
    if part is None:
        sources = ["SAM: no part found"] if step_perception is not None else []
        return Claim(field="part", status="unverified", sources=sources)
    if part.confidence is None:
        sources = [f"SAM: part '{part.concept}' found"]
    else:
        sources = [f"SAM: part '{part.concept}' found (confidence {part.confidence:.2f})"]
    named = same_part(part.concept, step.target_part)
    if not named:
        sources.append(f"the guide calls this part '{step.target_part}': the names differ")
    if named and part.confidence is not None and part.confidence >= PART_CONFIDENCE:
        status = "verified"
    else:
        status = "supported"
    return Claim(field="part", status=status, sources=sources)


def step_score(claims: list[Claim]) -> float:
    """Mean of verified 1 / supported 0.5 / unverified 0 (0 when there is no claim)."""
    if not claims:
        return 0.0
    return sum(SCORES[claim.status] for claim in claims) / len(claims)


def build_proof(
    plan: Plan,
    fusion: Fusion | None = None,
    refine: Refine | None = None,
    perception: Perception | None = None,
    transcript: Transcript | None = None,
) -> Proof:
    """One StepProof per plan step; the proof score is the mean of the step scores."""
    fused = {item.index: item for item in fusion.steps} if fusion else {}
    refined = {item.index: item for item in refine.steps} if refine else {}
    seen = {item.index: item for item in perception.steps} if perception else {}
    steps = []
    for step in plan.steps:
        source = step.source_index if step.source_index is not None else step.index
        found = seen.get(step.index)
        review = found.review if found else None
        claims = [
            boundaries_claim(step, fused.get(source), refined.get(source), review),
            instruction_claim(step, transcript, review),
        ]
        fasteners = fastener_claim(step, seen.get(step.index), refined.get(source))
        if fasteners is not None:
            claims.append(fasteners)
        part = part_claim(step, seen.get(step.index))
        # the old sentence named this part; the frames show something else, so nothing to prove
        dropped = rewritten_by_review(step, review) and part and part.status == "unverified"
        if part is not None and not dropped:
            claims.append(part)
        steps.append(StepProof(index=step.index, claims=claims, score=step_score(claims)))
    score = round(sum(item.score for item in steps) / len(steps), 3) if steps else 0.0
    return Proof(steps=steps, score=score)


def run(job_dir: Path, settings: Any) -> Proof:
    plan = artifacts.load(job_dir, Plan)
    proof = build_proof(
        plan,
        artifacts.load_optional(job_dir, Fusion),
        artifacts.load_optional(job_dir, Refine),
        artifacts.load_optional(job_dir, Perception),
        artifacts.load_optional(job_dir, Transcript),
    )
    artifacts.save(job_dir, proof)
    return proof
