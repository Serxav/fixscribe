from app import artifacts
from app.pipeline.publish import UNVERIFIED_SCREWS, build_guide, run, screws_verified
from app.schemas import Box, Frames, Guide, Plan, ScrewMap, Step, StepMedia


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
