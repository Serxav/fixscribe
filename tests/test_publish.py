from app import artifacts
from app.pipeline.publish import (
    PRO_ONLY_CHECK,
    PRO_ONLY_STEP,
    UNVERIFIED_SCREWS,
    build_guide,
    run,
    screws_verified,
)
from app.schemas import Box, Frames, Guide, Identity, Plan, Safety, ScrewMap, Step, StepMedia


def step(index, start, end, **extra):
    return Step(
        index=index, title=f"s{index}", instruction="...", start_s=start, end_s=end, **extra
    )


def plan(*steps, checks=()):
    return Plan(
        title="Replace battery",
        device="Phone X",
        mode="narrated",
        duration_s=30.0,
        steps=list(steps),
        checks=list(checks),
    )


def test_media_is_merged_by_step_index():
    frames = Frames(steps=[StepMedia(index=2, keyframe_s=12.5, image="steps/02.jpg", clip=None)])
    guide = build_guide(plan(step(1, 0, 10), step(2, 10, 20)), frames)
    assert guide.steps[0].image is None
    assert (guide.steps[1].image, guide.steps[1].keyframe_s) == ("steps/02.jpg", 12.5)


def test_unverified_screw_counts_are_said_honestly():
    counted = step(1, 0, 10, action="unscrew", removes=["cover"], screws=ScrewMap(count=4))
    guide = build_guide(plan(counted), None)
    assert UNVERIFIED_SCREWS in guide.checks
    assert not screws_verified(guide.steps)


def test_screws_with_positions_count_as_verified():
    boxes = [Box(number=n, x=0.1 * n, y=0.1, w=0.05, h=0.05) for n in (1, 2)]
    located = step(
        1, 0, 10, action="unscrew", removes=["cover"], screws=ScrewMap(count=2, boxes=boxes)
    )
    guide = build_guide(plan(located), None)
    assert UNVERIFIED_SCREWS not in guide.checks
    assert screws_verified(guide.steps)


def test_no_screws_no_screw_note():
    guide = build_guide(plan(step(1, 0, 10, action="disconnect", removes=["battery"])), None)
    assert not any("crew" in check for check in guide.checks)
    assert [r.action for r in guide.reassembly] == ["reconnect"]


def test_run_is_the_only_writer_of_guide_json(tmp_path):
    artifacts.save(tmp_path, plan(step(1, 0, 10), checks=["note from plan"]))
    run(tmp_path, settings=None)
    guide = artifacts.load(tmp_path, Guide)
    assert guide.checks[0] == "note from plan"
    assert guide.duration_s == 30.0


def perception_for(index, removed, notes=(), overlay="steps/01_overlay.jpg"):
    from app.schemas import NormBox, Perception, ScrewRecord, StepPerception

    records = [
        ScrewRecord(id=f"S{n}", number=n, box=NormBox(x=x, y=0.2, w=0.05, h=0.05))
        for n, x in enumerate(removed, start=1)
    ]
    return Perception(
        steps=[StepPerception(index=index, removed=records, overlay=overlay, notes=list(notes))]
    )


def test_sam_boxes_become_the_screw_map_and_verify_it():
    counted = step(1, 0, 10, action="unscrew", removes=["cover"], screws=ScrewMap(count=2))
    guide = build_guide(plan(counted), None, perception_for(1, [0.1, 0.6]))
    first = guide.steps[0]
    assert [b.number for b in first.screws.boxes] == [1, 2]
    assert first.overlay == "steps/01_overlay.jpg"
    assert UNVERIFIED_SCREWS not in guide.checks
    assert guide.reassembly[0].screws.boxes == first.screws.boxes  # same screws go back


def test_sam_disagreement_is_reported():
    counted = step(1, 0, 10, action="unscrew", removes=["cover"], screws=ScrewMap(count=4))
    note = "SAM found 3 screws removed, the analysis counted 4."
    guide = build_guide(plan(counted), None, perception_for(1, [0.1, 0.3, 0.6], notes=[note]))
    assert f"Step 1: {note}" in guide.checks
    assert any("4 screws counted but 3 located" in check for check in guide.checks)


def test_box_at_the_edge_is_kept_inside_the_image():
    counted = step(1, 0, 10, action="unscrew", removes=["cover"], screws=ScrewMap(count=1))
    guide = build_guide(plan(counted), None, perception_for(1, [0.98]))
    box = guide.steps[0].screws.boxes[0]
    assert box.x + box.w <= 1.0


def car(**extra):
    base = {"object_name": "family car", "category": "automotive", "task": "repair"}
    return Identity(**(base | extra))


def test_identity_and_safety_are_copied_into_the_guide():
    identity = car(language="es")
    safety = Safety(level="normal")
    guide = build_guide(plan(step(1, 0, 10)), None, identity=identity, safety=safety)
    assert guide.identity == identity
    assert guide.safety == safety
    assert guide.language == "es"


def test_automotive_steps_use_bolts():
    counted = step(1, 0, 10, action="unscrew", removes=["wheel"], screws=ScrewMap(count=2))
    guide = build_guide(plan(counted), None, identity=car())
    assert guide.steps[0].screws.kind == "bolt"
    assert guide.reassembly[0].screws.kind == "bolt"


def test_perception_screw_map_uses_the_domain_kind():
    loose = step(1, 0, 10, action="unscrew", removes=["wheel"])
    guide = build_guide(plan(loose), None, perception_for(1, [0.1, 0.6]), identity=car())
    assert guide.steps[0].screws.kind == "bolt"


def test_caution_puts_prechecks_first_without_duplicates():
    safety = Safety(level="caution", prechecks=["Switch the engine off and let it cool."])
    warned = plan(step(1, 0, 10), checks=[])
    warned = warned.model_copy(
        update={"warnings": ["Wear gloves.", "Switch the engine off and let it cool."]}
    )
    guide = build_guide(warned, None, identity=car(), safety=safety)
    assert guide.warnings == ["Switch the engine off and let it cool.", "Wear gloves."]
    assert guide.steps[0].instruction == "..."  # instructions are kept on caution


def test_professional_only_hides_instructions_and_reassembly():
    safety = Safety(
        level="professional_only",
        reasons=["Gas lines and appliances must be worked on by a certified gas technician."],
        prechecks=["Call a certified technician."],
    )
    counted = step(1, 0, 10, action="unscrew", removes=["cover"], screws=ScrewMap(count=2))
    guide = build_guide(plan(counted), None, identity=car(), safety=safety)
    assert [s.instruction for s in guide.steps] == [PRO_ONLY_STEP]
    assert guide.reassembly == []
    assert f"{PRO_ONLY_CHECK} Gas lines" in " ".join(guide.checks)
    assert guide.warnings[0] == "Call a certified technician."
    assert guide.steps[0].screws.kind == "bolt"  # the evidence stays, the words go


def test_no_identity_keeps_screw_kind():
    counted = step(1, 0, 10, action="unscrew", removes=["cover"], screws=ScrewMap(count=2))
    guide = build_guide(plan(counted), None)
    assert guide.steps[0].screws.kind == "screw"


def test_proof_is_copied_into_the_guide(tmp_path):
    from app.schemas import Claim, Proof, StepProof

    proof = Proof(
        steps=[
            StepProof(
                index=1,
                claims=[
                    Claim(field="boundaries", status="verified", sources=["voice cut at 1.0 s"])
                ],
                score=1.0,
            )
        ],
        score=1.0,
    )
    artifacts.save(tmp_path, plan(step(1, 0, 10)))
    assert run(tmp_path, settings=None).proof is None
    artifacts.save(tmp_path, proof)
    assert run(tmp_path, settings=None).proof == proof


def test_run_passes_identity_and_safety(tmp_path):
    identity = car()
    safety = Safety(level="caution", prechecks=["Switch the engine off and let it cool."])
    artifacts.save(tmp_path, plan(step(1, 0, 10)))
    artifacts.save(tmp_path, identity)
    artifacts.save(tmp_path, safety)
    guide = run(tmp_path, settings=None)
    assert guide.identity == identity
    assert guide.safety == safety
    assert guide.warnings[0] == "Switch the engine off and let it cool."


def test_unverified_note_names_the_fastener_kind():
    from app.pipeline.publish import UNVERIFIED_SCREWS, unverified_note

    assert unverified_note("bolt").startswith("The bolts count comes from the video analysis")
    assert unverified_note("glass").startswith("The glasses count")
    assert UNVERIFIED_SCREWS == unverified_note("screw")


def test_filming_note_only_for_small_videos_with_fasteners():
    from app.pipeline.publish import filming_note
    from app.schemas import IngestInfo, ScrewMap, SourceVideo, Step

    def ingest(width, height):
        source = SourceVideo(filename="original.mp4", width=width, height=height, duration_s=60)
        return IngestInfo.model_construct(source=source)

    screws = [Step(index=1, title="t", instruction="i", start_s=0, end_s=1,
                   screws=ScrewMap(count=2))]  # fmt: skip
    plain = [Step(index=1, title="t", instruction="i", start_s=0, end_s=1)]
    assert "720p" in filming_note(ingest(1280, 720), screws)
    assert filming_note(ingest(1920, 1080), screws) is None
    assert filming_note(ingest(1280, 720), plain) is None
    assert filming_note(None, screws) is None
