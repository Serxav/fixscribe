from app import artifacts
from app.pipeline import proof
from app.pipeline.proof import (
    boundaries_claim,
    build_proof,
    fastener_claim,
    instruction_claim,
    part_claim,
    run,
    step_score,
)
from app.schemas import (
    Claim,
    Evidence,
    Fusion,
    FusionStep,
    NormBox,
    PartHighlight,
    Plan,
    Proof,
    Refine,
    RefinedStep,
    ScrewMap,
    ScrewRecord,
    Step,
    StepPerception,
    StepReview,
    Transcript,
    Turn,
)


def step(index=1, start=0.0, end=10.0, **extra):
    return Step(
        index=index, title=f"s{index}", instruction="Do it.", start_s=start, end_s=end, **extra
    )


def fusion_step(index=1, start=0.0, end=10.0, start_source="voice", end_source="pause"):
    return FusionStep(
        index=index,
        start_s=start,
        end_s=end,
        start_source=start_source,
        end_source=end_source,
        agreement=0.9,
        confidence=0.9,
    )


def refined(index=1, start=12.6, end=20.1, confidence=0.9, screws=0):
    return RefinedStep(
        index=index,
        start_s=start,
        end_s=end,
        instruction="Do it again.",
        action="remove",
        screw_count=screws,
        confidence=confidence,
    )


def box(x=0.2):
    return NormBox(x=x, y=0.2, w=0.05, h=0.05)


def perception_step(index=1, removed=(), concept=None, confidence=None):
    part = None
    if concept is not None:
        part = PartHighlight(concept=concept, box=box(), confidence=confidence)
    records = [
        ScrewRecord(id=f"S{n}", number=n, box=box(x=x)) for n, x in enumerate(removed, start=1)
    ]
    return StepPerception(index=index, part=part, removed=records)


def plan_of(*steps):
    return Plan(title="Guide", device="Phone", mode="narrated", duration_s=60.0, steps=list(steps))


# --- boundaries ---


def test_boundaries_verified_with_signal_and_recheck():
    claim = boundaries_claim(step(), fusion_step(), refined())
    assert claim.field == "boundaries"
    assert claim.status == "verified"
    assert "voice cut at 0.0 s" in claim.sources
    assert "pause at 10.0 s" in claim.sources
    assert "timecode re-check: 12.6–20.1 s" in claim.sources


def test_boundaries_supported_with_signal_only():
    claim = boundaries_claim(step(), fusion_step(end_source="scene"), None)
    assert claim.status == "supported"
    assert "scene change at 10.0 s" in claim.sources


def test_boundaries_supported_with_recheck_only():
    claim = boundaries_claim(step(), None, refined())
    assert claim.status == "supported"
    assert claim.sources == ["timecode re-check: 12.6–20.1 s"]


def test_boundaries_unverified_without_signal_or_recheck():
    assert boundaries_claim(step(), None, None).status == "unverified"
    spark = fusion_step(start_source="spark", end_source="spark")
    weak = refined(confidence=0.5)
    claim = boundaries_claim(step(), spark, weak)
    assert claim.status == "unverified"
    assert claim.sources == []


# --- instruction ---


def test_instruction_verified_with_video_and_voice():
    evidence = [
        Evidence(t_s=14.0, source="video", text="screws out"),
        Evidence(t_s=10.2, source="audio", text="quita los tornillos"),
    ]
    claim = instruction_claim(step(evidence=evidence), None)
    assert claim.status == "verified"
    assert "video 14.0 s: screws out" in claim.sources
    assert "voice 10.2 s: 'quita los tornillos'" in claim.sources


def test_instruction_supported_with_video_only():
    evidence = [Evidence(t_s=14.0, source="video", text="screws out")]
    claim = instruction_claim(step(evidence=evidence), None)
    assert claim.status == "supported"


def test_instruction_quotes_overlapping_turns_max_two_cut_to_80():
    transcript = Transcript(
        mode="narrated",
        duration_s=60.0,
        transcript="",
        turns=[
            Turn(start_s=1.0, end_s=2.0, text="first " * 30),
            Turn(start_s=3.0, end_s=4.0, text="second turn here"),
            Turn(start_s=5.0, end_s=6.0, text="third turn here"),
            Turn(start_s=50.0, end_s=51.0, text="far away"),
        ],
    )
    claim = instruction_claim(step(), transcript)
    assert claim.status == "supported"
    assert claim.sources == [
        f"voice 1.0 s: '{('first ' * 30)[:80]}'",
        "voice 3.0 s: 'second turn here'",
    ]


def test_instruction_unverified_without_evidence_or_transcript():
    claim = instruction_claim(step(), None)
    assert claim.status == "unverified"
    assert claim.sources == []


# --- fasteners ---


def test_fastener_none_without_screws():
    assert fastener_claim(step(), None, None) is None
    assert fastener_claim(step(screws=ScrewMap(count=0)), None, None) is None


def test_fastener_verified_when_sam_count_matches():
    counted = step(screws=ScrewMap(count=2))
    claim = fastener_claim(counted, perception_step(removed=(0.1, 0.6)), None)
    assert claim.status == "verified"
    assert "SAM: 2 screws removed (before/after stills)" in claim.sources


def test_fastener_supported_when_sam_finds_a_different_count():
    counted = step(screws=ScrewMap(count=4))
    claim = fastener_claim(counted, perception_step(removed=(0.1,)), None)
    assert claim.status == "supported"


def test_fastener_supported_when_recheck_agrees():
    counted = step(screws=ScrewMap(count=2))
    claim = fastener_claim(counted, None, refined(screws=2))
    assert claim.status == "supported"
    assert "timecode re-check counted 2" in claim.sources


def test_fastener_unverified_without_perception_or_recheck():
    counted = step(screws=ScrewMap(count=2))
    claim = fastener_claim(counted, None, None)
    assert claim.status == "unverified"
    assert claim.sources == []


def test_fastener_uses_the_step_kind():
    counted = step(screws=ScrewMap(count=1, kind="bolt"))
    claim = fastener_claim(counted, perception_step(removed=(0.1,)), None)
    assert "SAM: 1 bolts removed (before/after stills)" in claim.sources


# --- part ---


def test_part_none_without_target():
    assert part_claim(step(), perception_step(concept="cover", confidence=0.9)) is None


def test_part_verified_with_confident_find():
    found = step(target_part="cover")
    claim = part_claim(found, perception_step(concept="cover", confidence=0.8))
    assert claim.status == "verified"
    assert claim.sources[0].startswith("SAM: part 'cover' found")


def test_part_supported_with_weak_or_missing_confidence():
    found = step(target_part="cover")
    assert part_claim(found, perception_step(concept="cover", confidence=0.3)).status == "supported"
    claim = part_claim(found, perception_step(concept="cover"))
    assert claim.status == "supported"
    assert claim.sources == ["SAM: part 'cover' found"]


def test_part_unverified_when_nothing_found_or_not_run():
    found = step(target_part="cover")
    assert part_claim(found, perception_step()).status == "unverified"
    assert part_claim(found, None).status == "unverified"
    assert part_claim(found, None).sources == []


# --- scores and assembly ---


def test_step_score_means_claims_and_zero_without_claims():
    claims = [
        Claim(field="boundaries", status="verified", sources=[]),
        Claim(field="instruction", status="supported", sources=[]),
        Claim(field="part", status="unverified", sources=[]),
    ]
    assert step_score(claims) == 0.5
    assert step_score([]) == 0.0


def test_build_proof_without_inputs_never_crashes():
    first = step(1, 0, 10, evidence=[Evidence(t_s=2.0, source="video", text="cover off")])
    proof = build_proof(plan_of(first, step(2, 10, 20)))
    assert [claim.status for claim in proof.steps[0].claims] == ["unverified", "supported"]
    assert [claim.status for claim in proof.steps[1].claims] == ["unverified", "unverified"]
    assert proof.score == 0.125


def test_build_proof_matches_steps_by_index_and_rounds_the_score():
    heard = [
        Evidence(t_s=2.0, source="video", text="cover off"),
        Evidence(t_s=3.0, source="audio", text="quita la tapa"),
    ]
    guide_plan = plan_of(step(1, 0, 10, evidence=heard), step(2, 10, 20), step(3, 20, 30))
    fusion = Fusion(
        candidates=3,
        steps=[fusion_step(1), fusion_step(2, start=10.0, end=20.0), fusion_step(3)],
    )
    refine = Refine(steps=[refined(1), refined(2), refined(3)])
    proof = build_proof(guide_plan, fusion, refine, None, None)
    assert [item.index for item in proof.steps] == [1, 2, 3]
    assert "voice cut at 10.0 s" in proof.steps[1].claims[0].sources
    assert [item.score for item in proof.steps] == [1.0, 0.5, 0.5]
    assert proof.score == 0.667


def test_run_writes_a_loadable_proof_json(tmp_path):
    first = step(evidence=[Evidence(t_s=2.0, source="audio", text="paso uno")])
    artifacts.save(tmp_path, plan_of(first))
    artifacts.save(tmp_path, Refine(steps=[refined()]))
    proof = run(tmp_path, settings=None)
    loaded = artifacts.load(tmp_path, Proof)
    assert loaded == proof
    assert loaded.steps[0].index == 1
    sources = [source for claim in loaded.steps[0].claims for source in claim.sources]
    assert any("timecode re-check" in source for source in sources)


def test_proof_pairs_refine_by_source_index_not_plan_index():
    from app.pipeline.proof import build_proof
    from app.schemas import Plan, Refine, RefinedStep, Step

    step = Step(index=1, title="t", instruction="i", start_s=0, end_s=2, source_index=2)
    plan = Plan.model_validate(
        {"title": "t", "device": "d", "mode": "silent", "duration_s": 10, "steps": [step]}
    )
    refined = RefinedStep(
        index=2, start_s=0, end_s=2, instruction="i", action="other", confidence=0.9
    )
    proof = build_proof(plan, refine=Refine(steps=[refined]))
    assert proof.steps[0].claims[0].status == "supported"  # the refine of draft 2 was used


def _reviewed(step, **fields):
    review = StepReview(**{"matches": True, "start_s": step.start_s, "end_s": step.end_s,
                           "confidence": 0.9, **fields})  # fmt: skip
    return proof.instruction_claim(step, None, review), proof.boundaries_claim(
        step, None, None, review
    )


def test_a_confident_frame_by_frame_review_proves_a_silent_step():
    step = Step(index=1, title="t", instruction="i", start_s=10, end_s=20)
    instruction, boundaries = _reviewed(step)
    assert instruction.status == "verified" and boundaries.status == "verified"


def test_a_review_that_disagrees_or_doubts_proves_nothing():
    step = Step(index=1, title="t", instruction="i", start_s=10, end_s=20)
    instruction, _ = _reviewed(step, matches=False, instruction="they pry the cover")
    assert instruction.status == "unverified" and "disagrees" in instruction.sources[-1]
    instruction, boundaries = _reviewed(step, confidence=0.4)
    assert instruction.status == "unverified" and boundaries.status == "unverified"
    _, boundaries = _reviewed(step, start_s=2.0)  # its times are far from the step's
    assert boundaries.status == "unverified"
