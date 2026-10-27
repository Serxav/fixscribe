import pytest
from pydantic import ValidationError

from app import artifacts
from app.artifacts import ArtifactError
from app.pipeline.plan import PlanError, apply_fusion, build_plan, clean_times, run
from app.schemas import (
    Analysis,
    DraftStep,
    Fusion,
    FusionStep,
    IngestInfo,
    Plan,
    Transcript,
)


def draft(title, start, end, **extra):
    return DraftStep(title=title, start_s=start, end_s=end, **extra)


def analysis(*steps):
    return Analysis(title="Replace battery", device="Phone X", steps=list(steps))


def test_clean_times_clamps_sorts_and_fixes_overlaps():
    drafts = [draft("b", 8, 20), draft("a", -1, 10), draft("c", 25, 99)]
    kept, notes = clean_times(drafts, duration_s=30)
    assert [(d.title, d.start_s, d.end_s) for d in kept] == [
        ("a", 0.0, 10.0),
        ("b", 10.0, 20.0),
        ("c", 25.0, 30.0),
    ]
    # Every real move is written down: the overlap of "b" and the end of "c".
    assert any("'b' overlapped" in note for note in notes)
    assert any("'c'" in note and "outside the video" in note for note in notes)


def test_clean_times_drops_steps_with_no_time_left():
    kept, notes = clean_times(
        [draft("a", 0, 10), draft("inside a", 2, 9), draft("late", 40, 50)], 30
    )
    assert [d.title for d in kept] == ["a"]
    assert sum("Dropped" in note for note in notes) == 2


def test_fusion_replaces_times_and_confidence_in_time_order():
    drafts = [draft("second", 10, 20, confidence=0.9), draft("first", 0, 10, confidence=0.9)]
    fusion = Fusion(
        candidates=2,
        steps=[
            FusionStep(index=1, start_s=0.5, end_s=9.6, start_source="voice", end_source="pause",
                       agreement=1.0, confidence=0.9),
            FusionStep(index=2, start_s=9.6, end_s=20.0, start_source="pause", end_source="spark",
                       agreement=0.8, confidence=0.72),
        ],
    )  # fmt: skip
    fused = apply_fusion(drafts, fusion)
    assert [(d.title, d.start_s, d.end_s, d.confidence) for d in fused] == [
        ("first", 0.5, 9.6, 0.9),
        ("second", 9.6, 20.0, 0.72),
    ]


def test_build_plan_flags_low_confidence_and_keeps_only_own_evidence():
    plan = build_plan(
        analysis(
            draft("a", 0, 5, evidence=[{"t_s": 2, "source": "video", "text": "ok"},
                                       {"t_s": 40, "source": "video", "text": "far"}]),
            draft("b", 5, 9, confidence=0.2,
                  evidence=[{"t_s": 1, "source": "audio", "text": "belongs to a"}]),
        ),
        None,
        10,
        "silent",
    )  # fmt: skip
    assert [e.text for e in plan.steps[0].evidence] == ["ok"]
    assert plan.steps[1].evidence == []
    assert plan.steps[1].review == "needs_review"
    assert any("review steps: 2" in c for c in plan.checks)


def test_empty_instruction_falls_back_to_title():
    plan = build_plan(analysis(draft("Remove SIM tray", 0, 5)), None, 10, "silent")
    assert plan.steps[0].instruction == "Remove SIM tray"


def test_out_of_range_numbers_from_spark_are_fixed_not_fatal():
    parsed = Analysis.model_validate(
        {
            "estimated_minutes": -5,
            "steps": [
                {"title": "a", "start_s": 0, "end_s": 5, "screw_count": -2, "confidence": 85,
                 "evidence": [{"t_s": -1.0, "source": "video", "text": "x"}]},
                {"title": "b", "start_s": 5, "end_s": 9, "confidence": 1.7e9},
            ],
        }
    )  # fmt: skip
    assert parsed.estimated_minutes == 0
    first, second = parsed.steps
    assert (first.screw_count, first.confidence, first.evidence[0].t_s) == (0, 0.85, 0.0)
    assert second.confidence == 1.0
    with pytest.raises(ValidationError):
        Analysis.model_validate({"steps": [{"title": "a", "start_s": "soon", "end_s": 1}]})


def job(tmp_path, *steps, transcript=None, fusion=None):
    artifacts.save(tmp_path, analysis(*steps))
    artifacts.save(tmp_path, IngestInfo(duration_s=12.0, width=720, height=1280, has_audio=True))
    if transcript:
        artifacts.save(tmp_path, transcript)
    if fusion:
        artifacts.save(tmp_path, fusion)
    return tmp_path


def test_run_writes_plan_json_and_reads_the_mode(tmp_path):
    job(tmp_path, draft("a", 0, 5), transcript=Transcript(mode="narrated"))
    run(tmp_path, settings=None)
    plan = artifacts.load(tmp_path, Plan)
    assert (plan.mode, plan.duration_s, len(plan.steps)) == ("narrated", 12.0, 1)
    assert not (tmp_path / "guide.json").exists()  # only publish writes the guide


def test_run_without_transcript_is_silent(tmp_path):
    assert run(job(tmp_path, draft("a", 0, 5)), settings=None).mode == "silent"


def test_run_fails_clearly(tmp_path):
    with pytest.raises(ArtifactError, match="missing analysis.json"):
        run(tmp_path, settings=None)
    job(tmp_path)
    with pytest.raises(PlanError, match="no repair steps"):
        run(tmp_path, settings=None)
    job(tmp_path, draft("after the end", 40, 50))
    with pytest.raises(PlanError, match="usable time range"):
        run(tmp_path, settings=None)


def test_refine_overrides_the_steps_it_looked_at():
    from app.schemas import Refine, RefinedStep

    drafts = [draft("open", 0, 10, screw_count=4, confidence=0.4), draft("lift", 10, 20)]
    refine = Refine(
        steps=[
            RefinedStep(index=1, start_s=1.5, end_s=9.0, instruction="Remove the 3 screws.",
                        action="unscrew", removes=["back cover"], screw_count=3, warnings=[],
                        confidence=0.85)
        ]
    )  # fmt: skip
    plan = build_plan(analysis(*drafts), None, 30, "narrated", refine)
    first, second = plan.steps
    assert (first.start_s, first.end_s, first.screws.count) == (1.5, 9.0, 3)
    assert first.instruction == "Remove the 3 screws."
    assert first.review == "auto"  # confidence went from 0.4 to 0.85
    assert (second.start_s, second.title) == (10.0, "lift")


def test_inverted_refine_answer_is_ignored():
    from app.schemas import Refine, RefinedStep

    refine = Refine(steps=[RefinedStep(index=1, start_s=9, end_s=2, instruction="x",
                                       action="other", confidence=0.9)])  # fmt: skip
    plan = build_plan(analysis(draft("a", 0, 10)), None, 30, "silent", refine)
    assert (plan.steps[0].start_s, plan.steps[0].end_s) == (0.0, 10.0)


def test_low_confidence_refine_answer_does_not_replace_a_good_step():
    from app.schemas import Refine, RefinedStep

    good = draft("disconnect", 5, 20, instruction="Disconnect the battery.", confidence=0.9)
    refine = Refine(steps=[RefinedStep(index=1, start_s=5, end_s=20, instruction="wrong step",
                                       action="unscrew", confidence=0.4)])  # fmt: skip
    plan = build_plan(analysis(good), None, 30, "silent", refine)
    assert plan.steps[0].instruction == "Disconnect the battery."


def test_run_reads_refine_json(tmp_path):
    from app.schemas import Refine, RefinedStep

    job(tmp_path, draft("a", 0, 10, confidence=0.4))
    refined = RefinedStep(
        index=1, start_s=2, end_s=8, instruction="Refined.", action="other", confidence=0.9
    )
    artifacts.save(tmp_path, Refine(steps=[refined]))
    assert run(tmp_path, settings=None).steps[0].instruction == "Refined."


def test_source_index_survives_a_dropped_step():
    from app.pipeline.plan import build_plan
    from app.schemas import Analysis

    analysis = Analysis.model_validate(
        {
            "title": "t",
            "device": "d",
            "steps": [
                {"title": "gone", "instruction": "x", "start_s": 50, "end_s": 60},  # after the end
                {"title": "a", "instruction": "x", "start_s": 1, "end_s": 5},
                {"title": "b", "instruction": "x", "start_s": 5, "end_s": 9},
            ],
        }
    )
    plan = build_plan(analysis, None, duration_s=10, mode="silent")
    assert [(s.title, s.index, s.source_index) for s in plan.steps] == [("a", 1, 1), ("b", 2, 2)]
